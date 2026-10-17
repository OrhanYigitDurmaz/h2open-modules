from collections import defaultdict

from odoo import Command, api, fields, models

# Product kinds that make an order a water delivery.
H2O_DELIVERY_KINDS = ('water_returnable', 'water_packaged', 'container')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    h2o_is_delivery = fields.Boolean(
        string="Water Delivery", compute='_compute_h2o_is_delivery', store=True, index=True,
        help="The order contains water or bottles to deliver.",
    )
    h2o_channel = fields.Selection(
        [
            ('phone', "Phone"),
            ('portal', "Customer App / Portal"),
            ('subscription', "Subscription"),
            ('driver', "Driver"),
            ('other', "Other"),
        ],
        string="Channel", default='phone', tracking=True,
    )
    h2o_delivery_date = fields.Date(
        string="Water Delivery Date", compute='_compute_h2o_delivery_date', store=True, readonly=False,
        precompute=True, index=True, tracking=True,
        help="Day the water is delivered. Defaults to the next delivery day of the delivery address.",
    )
    h2o_time_window = fields.Selection(
        [('any', "Any Time"), ('morning', "Morning"), ('afternoon', "Afternoon"), ('evening', "Evening")],
        string="Time Window", default='any',
    )
    h2o_zone_id = fields.Many2one(
        related='partner_shipping_id.h2o_zone_id', store=True, index=True, string="Delivery Zone",
    )
    h2o_empties_expected = fields.Integer(
        string="Empties Expected",
        help="Empty bottles the customer will hand back. A deposit is only charged for the bottles "
             "delivered beyond this number.",
    )
    h2o_delivery_state = fields.Selection(
        [
            ('to_plan', "To Plan"),
            ('planned', "Planned"),
            ('delivered', "Delivered"),
            ('failed', "Failed"),
            ('cancelled', "Cancelled"),
        ],
        string="Water Delivery Status", default='to_plan', copy=False, index=True, tracking=True,
    )
    h2o_delivery_notes = fields.Text(related='partner_shipping_id.h2o_delivery_notes', readonly=False)
    h2o_customer_type = fields.Selection(related='partner_id.commercial_partner_id.h2o_customer_type')
    h2o_payment_mode = fields.Selection(related='partner_id.commercial_partner_id.h2o_payment_mode')
    h2o_bottle_balance = fields.Integer(related='partner_id.h2o_bottle_balance', string="Bottles Held")

    @api.depends('order_line.product_id')
    def _compute_h2o_is_delivery(self):
        for order in self:
            order.h2o_is_delivery = any(
                kind in H2O_DELIVERY_KINDS for kind in order.order_line.product_id.mapped('h2o_product_kind')
            )

    @api.depends('partner_shipping_id')
    def _compute_h2o_delivery_date(self):
        for order in self:
            if order.partner_shipping_id and order.state in ('draft', 'sent', False):
                order.h2o_delivery_date = order.partner_shipping_id._h2o_next_delivery_date()

    def _h2o_returnable_qty_by_container(self):
        """Bottles delivered with the order lines, per container: ``{product: qty}``."""
        self.ensure_one()
        result = defaultdict(float)
        for line in self.order_line:
            container = line.product_id.h2o_container_product_id
            if line.display_type or line.product_id.h2o_product_kind != 'water_returnable' or not container:
                continue
            result[container] += line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
        return {container: int(round(qty)) for container, qty in result.items()}

    def _h2o_deposit_qty_by_product(self):
        """Deposit quantity to charge per deposit product: the bottles the
        customer ends up holding on top of the empties handed back."""
        self.ensure_one()
        empties = self.h2o_empties_expected
        result = defaultdict(int)
        for container, qty in sorted(self._h2o_returnable_qty_by_container().items(), key=lambda item: item[0].id):
            returned = min(qty, empties)
            empties -= returned
            if container.h2o_deposit_product_id:
                result[container.h2o_deposit_product_id] += qty - returned
        return result

    def action_h2o_update_deposit_lines(self):
        """Add, update or remove the deposit lines of the orders.

        One line per deposit product, for max(0, bottles delivered - empties
        expected). Lines whose quantity drops to zero are removed (set to 0
        on confirmed orders, which cannot lose lines).
        """
        for order in self.filtered(lambda o: o.state in ('draft', 'sent', 'sale')):
            targets = order._h2o_deposit_qty_by_product()
            deposit_lines = order.order_line.filtered(
                lambda line: not line.display_type and line.product_id.h2o_product_kind == 'deposit'
            )
            commands = []
            for product in targets.keys() | deposit_lines.product_id:
                qty = targets.get(product, 0)
                lines = deposit_lines.filtered(lambda line: line.product_id == product)
                if qty > 0 and not lines:
                    commands.append(Command.create({'product_id': product.id, 'product_uom_qty': qty}))
                    continue
                to_keep = lines[:1] if qty > 0 else lines.browse()
                if to_keep and to_keep.product_uom_qty != qty:
                    commands.append(Command.update(to_keep.id, {'product_uom_qty': qty, 'product_uom_id': product.uom_id.id}))
                for line in lines - to_keep:
                    if order.state == 'sale':
                        commands.append(Command.update(line.id, {'product_uom_qty': 0}))
                    else:
                        commands.append(Command.delete(line.id))
            if commands:
                order.order_line = commands
        return True

    def action_confirm(self):
        self.filtered('h2o_is_delivery').action_h2o_update_deposit_lines()
        return super().action_confirm()

    def _action_cancel(self):
        res = super()._action_cancel()
        self.filtered('h2o_is_delivery').h2o_delivery_state = 'cancelled'
        return res

    def action_draft(self):
        res = super().action_draft()
        self.filtered(lambda o: o.h2o_delivery_state == 'cancelled').h2o_delivery_state = 'to_plan'
        return res
