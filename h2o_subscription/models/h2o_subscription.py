import logging
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

FREQUENCY_DAYS = {'weekly': 7, 'biweekly': 14}


def h2o_following_date(day, frequency):
    """Delivery date following ``day`` for a frequency, on the same weekday.

    Weekly and every two weeks add 7 or 14 days. Monthly takes the same
    weekday in the same week of the next month (the 2nd Monday gives the 2nd
    Monday), or the last such weekday when that month has no such week.
    """
    if frequency in FREQUENCY_DAYS:
        return day + timedelta(days=FREQUENCY_DAYS[frequency])
    week = (day.day - 1) // 7
    first_of_month = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    first_weekday = first_of_month + timedelta(days=(day.weekday() - first_of_month.weekday()) % 7)
    result = first_weekday + timedelta(weeks=week)
    if result.month != first_of_month.month:
        result -= timedelta(weeks=1)
    return result


class H2oSubscription(models.Model):
    _name = 'h2o.subscription'
    _description = 'Water Subscription'
    _inherit = ['mail.thread']
    _order = 'state, next_date, id'
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default='/')
    partner_id = fields.Many2one(
        'res.partner', string="Customer", required=True, index=True, tracking=True, check_company=True,
        domain="[('h2o_customer_type', '!=', False), ('parent_id', '=', False)]",
    )
    address_id = fields.Many2one(
        'res.partner', string="Delivery Address", required=True, tracking=True, check_company=True,
        compute='_compute_address_id', store=True, readonly=False, precompute=True,
        domain="['|', ('id', '=', partner_id), ('parent_id', '=', partner_id)]",
    )
    line_ids = fields.One2many('h2o.subscription.line', 'subscription_id', string="Products", copy=True)
    frequency = fields.Selection(
        [('weekly', "Every Week"), ('biweekly', "Every Two Weeks"), ('monthly', "Every Month")],
        required=True, default='weekly', tracking=True,
        help="Monthly deliveries fall on the same weekday of the same week of the month "
             "(e.g. every 2nd Monday); when a month has no 5th such weekday, the last one is used.",
    )
    weekday_id = fields.Many2one(
        'h2o.weekday', string="Delivery Day", required=True, tracking=True,
        compute='_compute_weekday_id', store=True, readonly=False, precompute=True,
        help="Defaults to the weekday of the next delivery day of the address.",
    )
    next_date = fields.Date(
        string="Next Delivery", copy=False, index=True, tracking=True,
        help="Delivery date of the next order to create. Set on activation to the first delivery day "
             "on this weekday the customer can still be delivered (order cut-off hour respected).",
    )
    time_window = fields.Selection(
        selection=lambda self: self.env['sale.order']._fields['h2o_time_window'].selection,
        string="Time Window", required=True, default='any',
    )
    empties_expected = fields.Integer(
        compute='_compute_empties_expected', store=True, readonly=False, precompute=True,
        help="Empty bottles the customer hands back at each delivery. Defaults to the returnable "
             "bottles delivered, so a deposit is only charged for extra bottles.",
    )
    state = fields.Selection(
        [('draft', "Draft"), ('active', "Active"), ('paused', "Paused"), ('closed', "Closed")],
        required=True, default='draft', readonly=True, copy=False, index=True, tracking=True,
    )
    order_ids = fields.One2many('sale.order', 'h2o_subscription_id', string="Orders")
    order_count = fields.Integer(compute='_compute_order_count', string="Order Count")
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company)
    note = fields.Text(help="Printed on every order of the subscription.")

    @api.depends('partner_id')
    def _compute_address_id(self):
        for subscription in self:
            if subscription.address_id.commercial_partner_id != subscription.partner_id.commercial_partner_id:
                subscription.address_id = subscription.partner_id.address_get(['delivery'])['delivery'] \
                    if subscription.partner_id else False

    @api.depends('address_id')
    def _compute_weekday_id(self):
        for subscription in self:
            if not subscription.weekday_id and subscription.address_id:
                subscription.weekday_id = self.env['h2o.weekday']._h2o_from_date(
                    subscription.address_id._h2o_next_delivery_date())

    @api.depends('line_ids.product_id', 'line_ids.qty', 'line_ids.product_uom_id')
    def _compute_empties_expected(self):
        for subscription in self:
            subscription.empties_expected = int(sum(
                line.product_uom_id._compute_quantity(line.qty, line.product_id.uom_id)
                for line in subscription.line_ids
                if line.product_id.h2o_product_kind == 'water_returnable'
            ))

    def _compute_order_count(self):
        counts = dict(self.env['sale.order']._read_group(
            [('h2o_subscription_id', 'in', self.ids)], ['h2o_subscription_id'], ['__count'],
        ))
        for subscription in self:
            subscription.order_count = counts.get(subscription, 0)

    @api.constrains('next_date', 'weekday_id')
    def _check_next_date_weekday(self):
        for subscription in self:
            if subscription.next_date and subscription.next_date.weekday() != subscription.weekday_id.code:
                raise ValidationError(self.env._(
                    "The next delivery of %(subscription)s must be on a %(weekday)s.",
                    subscription=subscription.display_name, weekday=subscription.weekday_id.name))

    @api.onchange('weekday_id')
    def _onchange_weekday_id(self):
        if self.next_date and self.weekday_id:
            self.next_date = self._h2o_first_date(self.next_date)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('h2o.subscription') or '/'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_running(self):
        if any(subscription.state in ('active', 'paused') for subscription in self):
            raise UserError(self.env._("Close a subscription before deleting it."))

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------

    def _h2o_first_date(self, start=None):
        """First date on the subscription weekday, from ``start`` or else
        from the next day the address can still be delivered."""
        self.ensure_one()
        day = start or self.address_id._h2o_next_delivery_date()
        return day + timedelta(days=(self.weekday_id.code - day.weekday()) % 7)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _h2o_check_state(self, states):
        if any(subscription.state not in states for subscription in self):
            raise UserError(self.env._("This action is not possible in the current status of the subscription."))

    def _h2o_reset_next_date(self):
        """Restart from the first possible date when no date is set or it has passed."""
        for subscription in self:
            if not subscription.next_date or subscription.next_date < subscription.company_id._h2o_today():
                subscription.next_date = subscription._h2o_first_date()

    def action_activate(self):
        self._h2o_check_state(('draft',))
        for subscription in self:
            if not subscription.line_ids:
                raise UserError(self.env._("Add the products to deliver to %s.", subscription.display_name))
        self._h2o_reset_next_date()
        self.state = 'active'
        return True

    def action_pause(self):
        self._h2o_check_state(('active',))
        self.state = 'paused'
        return True

    def action_resume(self):
        self._h2o_check_state(('paused',))
        self._h2o_reset_next_date()
        self.state = 'active'
        return True

    def action_close(self):
        self._h2o_check_state(('draft', 'active', 'paused'))
        self.state = 'closed'
        return True

    def action_h2o_generate_now(self):
        """Create the order of the next delivery now, whatever the lead days."""
        self.ensure_one()
        self._h2o_check_state(('active',))
        order = self._h2o_generate_order()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_order.h2o_delivery_order_action')
        action.update({
            'domain': [('h2o_subscription_id', '=', self.id)],
            'context': {'default_h2o_subscription_id': self.id, 'default_h2o_channel': 'subscription'},
        })
        return action

    # ------------------------------------------------------------------
    # Order generation
    # ------------------------------------------------------------------

    def _h2o_prepare_order_values(self, delivery_date):
        """Values of the order delivered on ``delivery_date``, the same as a
        phone order of the customer."""
        self.ensure_one()
        return {
            'partner_id': self.partner_id.id,
            'partner_shipping_id': self.address_id.id,
            'company_id': self.company_id.id,
            'origin': self.name,
            'h2o_channel': 'subscription',
            'h2o_subscription_id': self.id,
            'h2o_delivery_date': delivery_date,
            'h2o_time_window': self.time_window,
            'h2o_empties_expected': self.empties_expected,
            'note': self.note,
            'order_line': [
                Command.create({
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty,
                    'product_uom_id': line.product_uom_id.id,
                })
                for line in self.line_ids
            ],
        }

    def _h2o_generate_order(self):
        """Create and confirm the order of ``next_date``, then move
        ``next_date`` to the following delivery. An existing order of the
        subscription for that date (even cancelled) is kept instead."""
        self.ensure_one()
        delivery_date = self.next_date
        order = self.env['sale.order'].search([
            ('h2o_subscription_id', '=', self.id), ('h2o_delivery_date', '=', delivery_date),
        ], limit=1)
        if not order:
            order = self.env['sale.order'].with_company(self.company_id).create(
                self._h2o_prepare_order_values(delivery_date))
            order.action_confirm()
            self.message_post(body=self.env._(
                "Order %(order)s created for %(date)s.",
                order=order._get_html_link(), date=fields.Date.to_string(delivery_date)))
        self.next_date = h2o_following_date(delivery_date, self.frequency)
        return order

    def _h2o_generate_due_orders(self, until):
        """Create the orders of active subscriptions due up to ``until``.

        Each subscription runs in its own savepoint: one that fails is
        logged and skipped, the others go on.
        """
        orders = self.env['sale.order']
        for subscription in self:
            created = self.env['sale.order']
            try:
                with self.env.cr.savepoint():
                    while subscription.state == 'active' and subscription.next_date and subscription.next_date <= until:
                        created |= subscription._h2o_generate_order()
                orders |= created
            except Exception as error:
                _logger.warning("Subscription %s: order not created: %s", subscription.name, error)
                subscription.message_post(body=self.env._("The order could not be created: %s", error))
        return orders

    @api.model
    def _cron_h2o_generate_orders(self):
        """Create the orders of active subscriptions whose next delivery is
        within the lead days of their company."""
        for company in self.env['res.company'].search([]):
            until = company._h2o_today() + timedelta(days=company.h2o_subscription_lead_days)
            self.search([
                ('state', '=', 'active'), ('company_id', '=', company.id), ('next_date', '<=', until),
            ])._h2o_generate_due_orders(until)


class H2oSubscriptionLine(models.Model):
    _name = 'h2o.subscription.line'
    _description = 'Water Subscription Product'
    _order = 'subscription_id, sequence, id'

    subscription_id = fields.Many2one('h2o.subscription', required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='subscription_id.company_id', store=True)
    product_id = fields.Many2one(
        'product.product', string="Product", required=True, check_company=True,
        domain="[('sale_ok', '=', True), ('h2o_product_kind', 'in', ('water_returnable', 'water_packaged', 'container'))]",
    )
    qty = fields.Float(string="Quantity", required=True, default=1.0, digits='Product Unit')
    product_uom_id = fields.Many2one(
        'uom.uom', string="Unit", required=True,
        compute='_compute_product_uom_id', store=True, readonly=False, precompute=True,
        domain="[('id', 'in', allowed_uom_ids)]",
    )
    allowed_uom_ids = fields.Many2many('uom.uom', compute='_compute_allowed_uom_ids')

    _qty_positive = models.Constraint('CHECK(qty > 0)', 'The quantity of a subscription product must be positive.')

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            if not line.product_uom_id or line.product_uom_id not in line.allowed_uom_ids:
                line.product_uom_id = line.product_id.uom_id

    @api.depends('product_id')
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = line.product_id._get_available_uoms()
