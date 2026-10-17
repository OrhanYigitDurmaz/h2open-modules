from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Fields that make up the ledger: they can only change on draft moves.
H2O_LEDGER_FIELDS = {'date', 'partner_id', 'product_id', 'qty_out', 'qty_in', 'deposit_amount', 'company_id'}


class H2oContainerMove(models.Model):
    _name = 'h2o.container.move'
    _description = 'Bottle Ledger Entry'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default='/')
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string="Customer", required=True, index=True, tracking=True,
        domain="[('parent_id', '=', False)]",
        help="The commercial partner holding the bottles; delivery addresses are stored separately.",
    )
    address_id = fields.Many2one(
        'res.partner', string="Delivery Address",
        domain="['|', ('id', '=', partner_id), ('parent_id', '=', partner_id)]",
    )
    product_id = fields.Many2one(
        'product.product', string="Container", required=True, index=True, tracking=True,
        domain="[('h2o_product_kind', '=', 'container')]",
    )
    qty_out = fields.Integer(string="Bottles Out", tracking=True, help="Bottles given to the customer.")
    qty_in = fields.Integer(string="Bottles In", tracking=True, help="Bottles taken back from the customer.")
    qty_balance = fields.Integer(
        string="Net", compute='_compute_qty_balance', store=True,
        help="Bottles out minus bottles in.",
    )
    deposit_amount = fields.Monetary(
        string="Deposit", tracking=True,
        help="Deposit charged (positive) or refunded (negative) with this entry.",
    )
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    source = fields.Selection(
        [
            ('delivery', "Delivery"),
            ('adjustment', "Adjustment"),
            ('opening', "Opening Balance"),
            ('closing', "Account Closing"),
        ],
        required=True, default='adjustment', tracking=True,
    )
    origin = fields.Char(help="Document this entry comes from, e.g. the order or stop.")
    origin_ref = fields.Reference(selection='_selection_origin_ref', string="Source Document")
    state = fields.Selection(
        [('draft', "Draft"), ('done', "Done"), ('cancel', "Cancelled")],
        required=True, default='draft', readonly=True, copy=False, index=True, tracking=True,
    )
    note = fields.Text()

    _qty_positive = models.Constraint(
        'CHECK(qty_out >= 0 AND qty_in >= 0)', 'Bottle quantities cannot be negative.',
    )
    _partner_product_index = models.Index('(partner_id, product_id) WHERE state = \'done\'')

    @api.model
    def _selection_origin_ref(self):
        return [(model.model, model.name) for model in self.env['ir.model'].sudo().search([('transient', '=', False)])]

    @api.depends('qty_out', 'qty_in')
    def _compute_qty_balance(self):
        for move in self:
            move.qty_balance = move.qty_out - move.qty_in

    @api.constrains('product_id')
    def _check_product_is_container(self):
        for move in self:
            if move.product_id.h2o_product_kind != 'container':
                raise ValidationError(self.env._(
                    "%s is not a returnable container product.", move.product_id.display_name))

    @api.constrains('product_id', 'qty_out', 'qty_in', 'deposit_amount')
    def _check_not_empty(self):
        for move in self:
            if not (move.qty_out or move.qty_in or move.currency_id.compare_amounts(move.deposit_amount, 0)):
                raise ValidationError(self.env._("A bottle ledger entry needs a quantity or a deposit amount."))

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and self.address_id.commercial_partner_id != self.partner_id.commercial_partner_id:
            self.address_id = False

    @api.onchange('product_id', 'qty_out', 'qty_in')
    def _onchange_h2o_deposit(self):
        """Propose the deposit for the net bottles moved."""
        deposit_product = self.product_id.h2o_deposit_product_id
        if deposit_product:
            self.deposit_amount = (self.qty_out - self.qty_in) * deposit_product.lst_price

    @api.model
    def _h2o_normalize_partner(self, vals):
        """Store the commercial partner, keeping the given contact as address."""
        if vals.get('partner_id'):
            partner = self.env['res.partner'].browse(vals['partner_id'])
            if partner.commercial_partner_id != partner:
                vals.setdefault('address_id', partner.id)
                vals['partner_id'] = partner.commercial_partner_id.id
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._h2o_normalize_partner(vals)
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('h2o.container.move') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if H2O_LEDGER_FIELDS.intersection(vals) and any(move.state == 'done' for move in self):
            raise UserError(self.env._(
                "Done bottle ledger entries cannot be changed. Cancel the entry and record a new one."))
        return super().write(self._h2o_normalize_partner(vals))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if any(move.state == 'done' for move in self):
            raise UserError(self.env._("Done bottle ledger entries cannot be deleted; cancel them instead."))

    def action_done(self):
        if any(move.state != 'draft' for move in self):
            raise UserError(self.env._("Only draft entries can be confirmed."))
        self.state = 'done'
        return True

    def action_cancel(self):
        self.filtered(lambda move: move.state != 'cancel').state = 'cancel'
        return True

    def action_draft(self):
        if any(move.state != 'cancel' for move in self):
            raise UserError(self.env._("Only cancelled entries can be reset to draft."))
        self.state = 'draft'
        return True

    @api.model
    def _h2o_record(self, partner, product, qty_out=0, qty_in=0, deposit_amount=0.0, source='delivery',
                    origin='', origin_ref=False, address=False, date=None):
        """Record a confirmed bottle movement for ``partner`` and return it.

        This is the entry point for other modules (deliveries, closings...).
        It runs as superuser so a driver's delivery can be recorded although
        drivers only read the ledger; callers must check their own rights.

        :param partner: customer or one of its addresses (``res.partner``)
        :param product: container product (``product.product``)
        :param origin_ref: record the movement comes from, or ``'model,id'``
        """
        if origin_ref and not isinstance(origin_ref, str):
            origin_ref = '%s,%s' % (origin_ref._name, origin_ref.id)
        commercial = partner.commercial_partner_id
        address = address or (partner if partner != commercial else False)
        move = self.sudo().create({
            'partner_id': commercial.id,
            'address_id': address and address.id,
            'product_id': product.id,
            'qty_out': qty_out,
            'qty_in': qty_in,
            'deposit_amount': deposit_amount,
            'source': source,
            'origin': origin,
            'origin_ref': origin_ref or False,
            'date': date or fields.Datetime.now(),
            'company_id': (commercial.company_id or self.env.company).id,
        })
        move.action_done()
        return self.browse(move.id)
