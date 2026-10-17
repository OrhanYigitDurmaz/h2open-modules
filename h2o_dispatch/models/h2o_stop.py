from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

# Fields a driver may change on a pending stop of their own trip. Everything
# else (state, quantities, order...) goes through the stop actions.
H2O_DRIVER_STOP_FIELDS = {
    'sequence', 'empties_collected', 'payment_method', 'payment_amount',
    'signature', 'photo', 'latitude', 'longitude', 'note', 'failure_note',
}
# Keys accepted by action_deliver() besides 'lines'.
H2O_DELIVER_FIELDS = (
    'empties_collected', 'payment_method', 'payment_amount', 'signature', 'photo', 'latitude', 'longitude', 'note',
)


class H2oStop(models.Model):
    _name = 'h2o.stop'
    _description = 'Delivery Stop'
    _order = 'trip_id, sequence, id'
    _check_company_auto = True

    trip_id = fields.Many2one('h2o.trip', string="Trip", required=True, index=True, ondelete='cascade',
                              check_company=True)
    sequence = fields.Integer(default=10)
    date = fields.Date(related='trip_id.date', store=True)
    driver_id = fields.Many2one(related='trip_id.driver_id', store=True, string="Driver")
    company_id = fields.Many2one(related='trip_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='trip_id.currency_id')
    order_id = fields.Many2one(
        'sale.order', string="Order", index=True, check_company=True,
        domain="[('state', '=', 'sale'), ('h2o_is_delivery', '=', True), ('h2o_delivery_state', '=', 'to_plan')]",
    )
    partner_id = fields.Many2one(
        'res.partner', string="Delivery Address", required=True, index=True,
        compute='_compute_partner_id', store=True, readonly=False, precompute=True,
    )
    commercial_partner_id = fields.Many2one(related='partner_id.commercial_partner_id', store=True, string="Customer")
    zone_id = fields.Many2one(related='partner_id.h2o_zone_id', string="Zone")
    state = fields.Selection(
        [('pending', "Pending"), ('delivered', "Delivered"), ('failed', "Failed"), ('skipped', "Skipped")],
        required=True, default='pending', readonly=True, copy=False, index=True,
    )
    failure_reason = fields.Selection(
        [
            ('not_home', "Nobody Home"),
            ('refused', "Refused"),
            ('no_access', "No Access"),
            ('no_payment', "No Payment"),
            ('other', "Other"),
        ],
        readonly=True,
    )
    failure_note = fields.Text()
    line_ids = fields.One2many('h2o.stop.line', 'stop_id', string="Products", copy=True)
    empties_collected = fields.Integer(
        help="Empty bottles taken back. Defaults to the empties expected on the order when delivering.",
    )
    empties_product_id = fields.Many2one(
        'product.product', string="Empty Bottle", domain="[('h2o_product_kind', '=', 'container')]",
        default=lambda self: self.env.ref('h2o_container.product_bottle_19l', raise_if_not_found=False),
    )
    payment_method = fields.Selection(
        [('cash', "Cash"), ('card', "Card"), ('account', "On Account"), ('none', "None")],
        compute='_compute_payment_method', store=True, readonly=False, precompute=True,
    )
    payment_amount = fields.Monetary(
        string="Amount Collected",
        help="Paid on delivery. Defaults to the amount due for cash and card payments.",
    )
    amount_due = fields.Monetary(
        compute='_compute_amount_due', store=True, compute_sudo=True,
        help="Order total, taxes included, for the quantities delivered (planned while pending).",
    )
    signature = fields.Binary(attachment=True, copy=False)
    photo = fields.Binary(attachment=True, copy=False)
    latitude = fields.Float(digits=(10, 7), copy=False)
    longitude = fields.Float(digits=(10, 7), copy=False)
    done_at = fields.Datetime(readonly=True, copy=False)
    note = fields.Text()
    time_window = fields.Selection(related='order_id.h2o_time_window')

    @api.depends('order_id')
    def _compute_partner_id(self):
        for stop in self:
            if stop.order_id:
                stop.partner_id = stop.order_id.partner_shipping_id

    @api.depends('order_id', 'partner_id')
    def _compute_payment_method(self):
        for stop in self:
            customer = stop.order_id.partner_id or stop.partner_id
            stop.payment_method = customer.commercial_partner_id.h2o_payment_mode or 'none'

    @api.depends(
        'state', 'line_ids.qty_planned', 'line_ids.qty_delivered',
        'line_ids.sale_line_id.price_unit', 'line_ids.sale_line_id.discount', 'line_ids.sale_line_id.tax_ids',
    )
    def _compute_amount_due(self):
        AccountTax = self.env['account.tax']
        for stop in self:
            if stop.state in ('failed', 'skipped'):
                stop.amount_due = 0.0
                continue
            qty_field = 'qty_delivered' if stop.state == 'delivered' else 'qty_planned'
            base_lines = [
                line.sale_line_id._prepare_base_line_for_taxes_computation(quantity=line[qty_field])
                for line in stop.line_ids if line.sale_line_id
            ]
            company = stop.order_id.company_id or stop.company_id or self.env.company
            AccountTax._add_tax_details_in_base_lines(base_lines, company)
            AccountTax._round_base_lines_tax_details(base_lines, company)
            stop.amount_due = sum(line['tax_details']['total_included_currency'] for line in base_lines)

    @api.depends('trip_id.name', 'partner_id')
    def _compute_display_name(self):
        for stop in self:
            stop.display_name = ' - '.join(filter(None, (stop.trip_id.name, stop.partner_id.display_name)))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        stops = super().create(vals_list)
        for stop in stops:
            if stop.order_id and not stop.line_ids:
                stop.line_ids = [fields.Command.create(vals) for vals in stop._h2o_line_vals_from_order()]
        stops.filtered(lambda s: s.state == 'pending').order_id.filtered(
            lambda o: o.h2o_delivery_state == 'to_plan'
        ).h2o_delivery_state = 'planned'
        return stops

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group('h2o_base.group_h2o_dispatcher'):
            if set(vals) - H2O_DRIVER_STOP_FIELDS or any(stop.state != 'pending' for stop in self):
                raise AccessError(self.env._("Drivers can only update their pending stops through the driver app."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if any(stop.state == 'delivered' for stop in self):
            raise UserError(self.env._("Delivered stops cannot be deleted."))

    def unlink(self):
        orders = self.filtered(lambda s: s.state == 'pending').order_id
        res = super().unlink()
        orders._h2o_release_planned()
        return res

    def _h2o_line_vals_from_order(self):
        """Stop lines for every product line of the order."""
        self.ensure_one()
        return [
            {
                'product_id': line.product_id.id,
                'sale_line_id': line.id,
                'qty_planned': line.product_uom_qty - line.qty_delivered,
            }
            for line in self.order_id.order_line
            if not line.display_type and line.product_id and line.product_uom_qty > line.qty_delivered
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _h2o_check_can_act(self):
        """Check the current user may deliver, fail or skip the stops."""
        self.check_access('write')
        self.trip_id._h2o_check_driver()
        for stop in self:
            if stop.state != 'pending':
                raise UserError(self.env._("Stop %s is already done.", stop.display_name))
            if stop.trip_id.state != 'on_road':
                raise UserError(self.env._(
                    "Start trip %s before delivering, failing or skipping its stops.", stop.trip_id.name))

    def action_deliver(self, vals=None):
        """Deliver the stops.

        :param dict vals: what happened at the door, all optional:
            ``lines`` (``[{'product_id', 'qty_delivered'}]``, products not
            listed are delivered as planned; deposits follow the bottles
            delivered and the empties collected), ``empties_collected``
            (default: empties expected on the order), ``payment_method``,
            ``payment_amount`` (default: amount due for cash and card),
            ``signature`` and ``photo`` (base64), ``latitude``,
            ``longitude``, ``note``.

        Updates the delivered quantities of the order, its delivery status
        and the customer's bottle ledger, then calls ``_h2o_on_delivered()``.
        """
        vals = dict(vals or {})
        unknown = set(vals) - set(H2O_DELIVER_FIELDS) - {'lines'}
        if unknown:
            raise UserError(self.env._("Unknown delivery values: %s", ', '.join(sorted(unknown))))
        self._h2o_check_can_act()
        for stop in self:
            stop._h2o_deliver(vals)
        self._h2o_on_delivered()
        return True

    def _h2o_deliver(self, vals):
        self.ensure_one()
        qty_by_product = {}
        for line_vals in vals.get('lines') or []:
            product_id = line_vals.get('product_id')
            if product_id not in self.line_ids.product_id.ids:
                raise UserError(self.env._("Product %s is not on this stop.", product_id))
            qty = line_vals.get('qty_delivered', 0)
            if not isinstance(qty, (int, float)) or qty < 0:
                raise UserError(self.env._("Delivered quantities must be positive numbers."))
            qty_by_product[product_id] = qty

        empties = vals.get('empties_collected', self.order_id.sudo().h2o_empties_expected)
        if not isinstance(empties, int) or empties < 0:
            raise UserError(self.env._("Empties collected must be a positive whole number."))
        stop_vals = {key: vals[key] for key in H2O_DELIVER_FIELDS if key in vals}
        stop_vals['empties_collected'] = empties

        # The lines and the state are written by the action, not by the user.
        lines = self.sudo().line_ids
        deposit_lines = lines.filtered(lambda l: l.product_id.h2o_product_kind == 'deposit')
        for line in lines - deposit_lines:
            line.qty_delivered = qty_by_product.get(line.product_id.id, line.qty_planned)
        deposit_qty = self._h2o_deposit_qty(empties)
        for line in deposit_lines:
            line.qty_delivered = qty_by_product.get(line.product_id.id, deposit_qty.get(line.product_id, 0))
        self.sudo().write({'state': 'delivered', 'done_at': fields.Datetime.now()})

        if 'payment_amount' not in stop_vals:
            method = stop_vals.get('payment_method', self.payment_method)
            stop_vals['payment_amount'] = self.amount_due if method in ('cash', 'card') else 0.0
        self.sudo().write(stop_vals)

        for line in lines.filtered('sale_line_id'):
            line.sale_line_id.qty_delivered += line.qty_delivered
        self._h2o_record_bottles()
        self.order_id.sudo().h2o_delivery_state = 'delivered'

    def _h2o_deposit_qty(self, empties):
        """Deposits to charge per deposit product: bottles delivered beyond
        the empties collected (same rule as the order's deposit lines)."""
        self.ensure_one()
        remaining = empties
        result = defaultdict(int)
        delivered = self.sudo().line_ids._h2o_bottle_qty('qty_delivered')
        for container, qty in sorted(delivered.items(), key=lambda item: item[0].id):
            returned = min(qty, remaining) if container == self.empties_product_id else 0
            remaining -= returned
            if container.h2o_deposit_product_id:
                result[container.h2o_deposit_product_id] += qty - returned
        return result

    def _h2o_record_bottles(self):
        """Record the bottles given, taken back and the deposits on the ledger."""
        self.ensure_one()
        lines = self.sudo().line_ids
        moves = defaultdict(lambda: {'qty_out': 0, 'qty_in': 0, 'deposit_amount': 0.0})
        for container, qty in lines._h2o_bottle_qty('qty_delivered').items():
            moves[container]['qty_out'] += qty
        if self.empties_collected and self.empties_product_id:
            moves[self.empties_product_id]['qty_in'] += self.empties_collected
        for line in lines.filtered(lambda l: l.product_id.h2o_product_kind == 'deposit' and l.qty_delivered):
            container = self.env['product.product'].search(
                [('h2o_deposit_product_id', '=', line.product_id.id)], limit=1)
            if container:
                price = line.sale_line_id.price_unit * (1 - (line.sale_line_id.discount or 0.0) / 100.0)
                moves[container]['deposit_amount'] += line.qty_delivered * price
        Move = self.env['h2o.container.move']
        for container, move_vals in moves.items():
            if move_vals['qty_out'] or move_vals['qty_in'] or move_vals['deposit_amount']:
                Move._h2o_record(
                    self.partner_id, container, source='delivery',
                    origin=self.order_id.name or self.trip_id.name, origin_ref=self,
                    **move_vals,
                )

    def action_fail(self, reason, note=None):
        """The delivery failed: the order goes back to planning."""
        if reason not in dict(self._fields['failure_reason'].selection):
            raise UserError(self.env._("Unknown failure reason: %s", reason))
        self._h2o_check_can_act()
        self.sudo().write({
            'state': 'failed',
            'failure_reason': reason,
            'failure_note': note or False,
            'done_at': fields.Datetime.now(),
        })
        self.order_id._h2o_release_planned()
        self._h2o_on_failed()
        return True

    def action_skip(self):
        """The driver could not get to the stop: the order goes back to planning."""
        self._h2o_check_can_act()
        self._h2o_set_skipped()
        return True

    def _h2o_set_skipped(self):
        self.sudo().write({'state': 'skipped', 'done_at': fields.Datetime.now()})
        self.order_id._h2o_release_planned()

    # ------------------------------------------------------------------
    # Hooks for other modules. They run as the acting user (possibly a
    # driver, after the action checked their rights).
    # ------------------------------------------------------------------

    def _h2o_on_delivered(self):
        """Called after the stops were delivered (billing invoices here)."""

    def _h2o_on_failed(self):
        """Called after the stops failed."""


class H2oStopLine(models.Model):
    _name = 'h2o.stop.line'
    _description = 'Delivery Stop Product'
    _order = 'stop_id, id'

    stop_id = fields.Many2one('h2o.stop', required=True, index=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Product", required=True)
    sale_line_id = fields.Many2one('sale.order.line', string="Order Line", index='btree_not_null')
    product_uom_id = fields.Many2one(
        'uom.uom', string="Unit", compute='_compute_product_uom_id', store=True, compute_sudo=True,
    )
    qty_planned = fields.Float(string="Planned", digits='Product Unit')
    qty_delivered = fields.Float(string="Delivered", digits='Product Unit', copy=False)

    @api.depends('sale_line_id.product_uom_id', 'product_id')
    def _compute_product_uom_id(self):
        for line in self:
            line.product_uom_id = line.sale_line_id.product_uom_id or line.product_id.uom_id

    def _h2o_bottle_qty(self, qty_field):
        """Returnable bottles of the lines per container: ``{container: qty}``,
        in units of the container, for ``qty_field`` (planned or delivered)."""
        result = defaultdict(int)
        for line in self:
            container = line.product_id.h2o_container_product_id
            if line.product_id.h2o_product_kind != 'water_returnable' or not container:
                continue
            qty = line.product_uom_id._compute_quantity(line[qty_field], line.product_id.uom_id)
            result[container] += int(round(qty))
        return dict(result)
