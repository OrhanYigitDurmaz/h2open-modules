from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class H2oQuickOrder(models.TransientModel):
    _name = 'h2o.quick.order'
    _description = 'Quick Phone Order'

    partner_id = fields.Many2one(
        'res.partner', string="Customer", required=True,
        domain="[('h2o_customer_type', '!=', False)]",
    )
    partner_shipping_id = fields.Many2one(
        'res.partner', string="Delivery Address", required=True,
        compute='_compute_partner_shipping_id', store=True, readonly=False, precompute=True,
        domain="['|', ('id', '=', partner_id), ('parent_id', '=', partner_id)]",
    )
    line_ids = fields.One2many(
        'h2o.quick.order.line', 'wizard_id', string="Products",
        compute='_compute_line_ids', store=True, readonly=False, precompute=True,
    )
    empties_expected = fields.Integer(
        compute='_compute_empties_expected', store=True, readonly=False, precompute=True,
        help="Empty bottles the customer will hand back. Defaults to the returnable bottles ordered, "
             "up to the bottles the customer holds.",
    )
    delivery_date = fields.Date(
        compute='_compute_delivery_date', store=True, readonly=False, precompute=True, required=True,
    )
    time_window = fields.Selection(
        selection=lambda self: self.env['sale.order']._fields['h2o_time_window'].selection,
        default='any', required=True,
    )
    note = fields.Text()
    delivery_notes = fields.Text(related='partner_shipping_id.h2o_delivery_notes', string="Delivery Notes")
    payment_mode = fields.Selection(related='partner_id.h2o_payment_mode')
    bottle_balance = fields.Integer(related='partner_id.h2o_bottle_balance', string="Bottles Held")
    zone_id = fields.Many2one(related='partner_shipping_id.h2o_zone_id', string="Zone")

    @api.depends('partner_id')
    def _compute_partner_shipping_id(self):
        for wizard in self:
            wizard.partner_shipping_id = wizard.partner_id.address_get(['delivery'])['delivery'] \
                if wizard.partner_id else False

    @api.depends('partner_id')
    def _compute_line_ids(self):
        """Repeat the water of the customer's last delivery order, or one 19 L bottle."""
        default_water = self.env.ref('h2o_container.product_water_19l', raise_if_not_found=False)
        for wizard in self:
            if not wizard.partner_id or wizard.line_ids:
                continue
            last_order = self.env['sale.order'].search([
                ('partner_id', 'child_of', wizard.partner_id.commercial_partner_id.id),
                ('h2o_is_delivery', '=', True),
                ('state', '=', 'sale'),
            ], order='date_order desc, id desc', limit=1)
            lines = [
                Command.create({'product_id': line.product_id.id, 'qty': line.product_uom_qty,
                                'product_uom_id': line.product_uom_id.id})
                for line in last_order.order_line
                if line.product_id.h2o_product_kind in ('water_returnable', 'water_packaged')
            ]
            if not lines and default_water and default_water.active:
                lines = [Command.create({'product_id': default_water.id, 'qty': 1})]
            wizard.line_ids = lines

    @api.depends('line_ids.product_id', 'line_ids.qty', 'partner_id')
    def _compute_empties_expected(self):
        for wizard in self:
            returnable = sum(
                line.qty for line in wizard.line_ids if line.product_id.h2o_product_kind == 'water_returnable'
            )
            wizard.empties_expected = max(0, min(int(returnable), wizard.partner_id.h2o_bottle_balance))

    @api.depends('partner_shipping_id')
    def _compute_delivery_date(self):
        for wizard in self:
            address = wizard.partner_shipping_id or wizard.partner_id
            wizard.delivery_date = address._h2o_next_delivery_date() if address else fields.Date.context_today(self)

    def _prepare_order_values(self):
        self.ensure_one()
        return {
            'partner_id': self.partner_id.id,
            'partner_shipping_id': self.partner_shipping_id.id,
            'h2o_channel': 'phone',
            'h2o_delivery_date': self.delivery_date,
            'h2o_time_window': self.time_window,
            'h2o_empties_expected': self.empties_expected,
            'note': self.note,
            'order_line': [
                Command.create({
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty,
                    **({'product_uom_id': line.product_uom_id.id} if line.product_uom_id else {}),
                })
                for line in self.line_ids
            ],
        }

    def action_create_order(self):
        """Create and confirm the sales order, then open it."""
        self.ensure_one()
        if not self.line_ids or any(line.qty <= 0 for line in self.line_ids):
            raise UserError(self.env._("Add at least one product, with a quantity above zero."))
        order = self.env['sale.order'].create(self._prepare_order_values())
        order.action_confirm()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }


class H2oQuickOrderLine(models.TransientModel):
    _name = 'h2o.quick.order.line'
    _description = 'Quick Phone Order Line'

    wizard_id = fields.Many2one('h2o.quick.order', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string="Product", required=True,
        domain="[('sale_ok', '=', True), ('h2o_product_kind', 'in', ('water_returnable', 'water_packaged', 'container'))]",
    )
    qty = fields.Float(string="Quantity", default=1.0, digits='Product Unit')
    product_uom_id = fields.Many2one(
        'uom.uom', string="Unit",
        compute='_compute_product_uom_id', store=True, readonly=False, precompute=True,
        domain="[('id', 'in', allowed_uom_ids)]",
    )
    allowed_uom_ids = fields.Many2many('uom.uom', compute='_compute_allowed_uom_ids')

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            if not line.product_uom_id or line.product_uom_id not in line.allowed_uom_ids:
                line.product_uom_id = line.product_id.uom_id

    @api.depends('product_id')
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = line.product_id._get_available_uoms()
