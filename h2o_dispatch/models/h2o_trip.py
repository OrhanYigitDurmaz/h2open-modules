from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

# Stop states a trip can be closed with.
H2O_STOP_DONE_STATES = ('delivered', 'failed', 'skipped')


class H2oTrip(models.Model):
    _name = 'h2o.trip'
    _description = 'Delivery Trip'
    _inherit = ['mail.thread']
    _order = 'date desc, route_id, id desc'
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default='/')
    date = fields.Date(required=True, default=fields.Date.context_today, index=True, tracking=True)
    route_id = fields.Many2one('h2o.route', string="Route", index=True, tracking=True, check_company=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string="Vehicle", tracking=True, check_company=True,
        compute='_compute_vehicle_id', store=True, readonly=False, precompute=True,
        domain="[('h2o_is_delivery_vehicle', '=', True)]",
    )
    driver_id = fields.Many2one(
        'res.users', string="Driver", index=True, tracking=True,
        compute='_compute_driver_id', store=True, readonly=False, precompute=True,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('h2o_base.group_h2o_driver').ids)],
    )
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection(
        [
            ('planned', "Planned"),
            ('loaded', "Loaded"),
            ('on_road', "On the Road"),
            ('closed', "Closed"),
            ('cancelled', "Cancelled"),
        ],
        required=True, default='planned', readonly=True, copy=False, index=True, tracking=True,
    )
    stop_ids = fields.One2many('h2o.stop', 'trip_id', string="Stops", copy=False)
    stop_count = fields.Integer(compute='_compute_stop_counts', store=True, string="Stops Count")
    pending_count = fields.Integer(compute='_compute_stop_counts', store=True, string="Pending")
    delivered_count = fields.Integer(compute='_compute_stop_counts', store=True, string="Delivered")
    failed_count = fields.Integer(
        compute='_compute_stop_counts', store=True, string="Failed",
        help="Stops failed or skipped.",
    )
    planned_bottle_qty = fields.Integer(
        string="Bottles Planned", compute='_compute_planned_bottle_qty',
        help="Full returnable bottles to deliver on the pending and delivered stops.",
    )
    load_qty = fields.Integer(
        string="Bottles Loaded", tracking=True,
        help="Full bottles loaded on the vehicle. Set to the bottles planned when loading if empty.",
    )
    returned_full_qty = fields.Integer(
        string="Full Bottles Returned", tracking=True,
        help="Full bottles brought back to the depot. Computed when the trip closes.",
    )
    returned_empty_qty = fields.Integer(
        string="Empties Returned", tracking=True,
        help="Empty bottles brought back to the depot. Computed when the trip closes.",
    )
    cash_expected = fields.Monetary(
        compute='_compute_cash_expected', store=True,
        help="Cash collected on the delivered stops, to be handed in by the driver.",
    )
    cash_handed_in = fields.Monetary(tracking=True, help="Cash the driver handed in after the trip.")
    last_latitude = fields.Float(digits=(10, 7), readonly=True)
    last_longitude = fields.Float(digits=(10, 7), readonly=True)
    last_position_at = fields.Datetime(string="Last Position", readonly=True)
    note = fields.Text()

    @api.depends('route_id')
    def _compute_vehicle_id(self):
        for trip in self:
            if trip.route_id.vehicle_id:
                trip.vehicle_id = trip.route_id.vehicle_id

    @api.depends('route_id', 'vehicle_id')
    def _compute_driver_id(self):
        for trip in self:
            driver = trip.route_id._h2o_driver() if trip.route_id else trip.vehicle_id.h2o_driver_user_id
            if driver:
                trip.driver_id = driver

    @api.depends('stop_ids.state')
    def _compute_stop_counts(self):
        for trip in self:
            states = trip.stop_ids.mapped('state')
            trip.stop_count = len(states)
            trip.pending_count = states.count('pending')
            trip.delivered_count = states.count('delivered')
            trip.failed_count = states.count('failed') + states.count('skipped')

    @api.depends('stop_ids.state', 'stop_ids.line_ids.qty_planned')
    def _compute_planned_bottle_qty(self):
        for trip in self:
            trip.planned_bottle_qty = sum(
                trip.stop_ids.filtered(lambda s: s.state in ('pending', 'delivered'))
                .line_ids._h2o_bottle_qty('qty_planned').values()
            )

    @api.depends('stop_ids.state', 'stop_ids.payment_method', 'stop_ids.payment_amount')
    def _compute_cash_expected(self):
        for trip in self:
            trip.cash_expected = sum(
                trip.stop_ids.filtered(lambda s: s.state == 'delivered' and s.payment_method == 'cash')
                .mapped('payment_amount')
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('h2o.trip') or '/'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_started(self):
        if any(trip.state not in ('planned', 'cancelled') for trip in self):
            raise UserError(self.env._("Only planned or cancelled trips can be deleted."))

    def unlink(self):
        # Through the ORM so the orders of pending stops go back to planning.
        self.stop_ids.unlink()
        return super().unlink()

    # ------------------------------------------------------------------
    # Access helpers
    # ------------------------------------------------------------------

    def _h2o_check_driver(self):
        """Check the current user may run the trips: dispatchers run any trip,
        drivers only their own. Drivers only read trips, so the actions write
        through ``sudo()`` once this check passed."""
        self.check_access('read')
        if self.env.su or self.env.user.has_group('h2o_base.group_h2o_dispatcher'):
            return
        if any(trip.driver_id != self.env.user for trip in self):
            raise AccessError(self.env._("You can only act on your own trips."))

    def _h2o_check_dispatcher(self):
        if not (self.env.su or self.env.user.has_group('h2o_base.group_h2o_dispatcher')):
            raise AccessError(self.env._("Only dispatchers can do this."))

    def _h2o_check_state(self, states, action):
        for trip in self:
            if trip.state not in states:
                raise UserError(self.env._(
                    "Trip %(trip)s cannot be %(action)s in state %(state)s.",
                    trip=trip.name, action=action,
                    state=dict(self._fields['state']._description_selection(self.env))[trip.state],
                ))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_load(self):
        """The vehicle is loaded at the depot."""
        self._h2o_check_driver()
        self._h2o_check_state(('planned',), self.env._("loaded"))
        for trip in self:
            if not trip.vehicle_id or not trip.driver_id:
                raise UserError(self.env._("Set a vehicle and a driver on trip %s before loading it.", trip.name))
            vals = {'state': 'loaded'}
            if not trip.load_qty:
                vals['load_qty'] = trip.planned_bottle_qty
            trip.sudo().write(vals)
        self._h2o_on_loaded()
        return True

    def action_start(self):
        """The driver leaves the depot. A planned trip is loaded first."""
        self._h2o_check_driver()
        self._h2o_check_state(('planned', 'loaded'), self.env._("started"))
        self.filtered(lambda t: t.state == 'planned').action_load()
        self.sudo().write({'state': 'on_road'})
        self._h2o_on_started()
        return True

    def action_close(self):
        """The driver is back: every stop must be delivered, failed or skipped."""
        self._h2o_check_driver()
        self._h2o_check_state(('loaded', 'on_road'), self.env._("closed"))
        for trip in self:
            pending = trip.stop_ids.filtered(lambda s: s.state not in H2O_STOP_DONE_STATES)
            if pending:
                raise UserError(self.env._(
                    "Trip %(trip)s still has %(count)s stop(s) to deliver, fail or skip.",
                    trip=trip.name, count=len(pending),
                ))
            stops = trip.stop_ids.filtered(lambda s: s.state == 'delivered')
            delivered_bottles = sum(stops.line_ids._h2o_bottle_qty('qty_delivered').values())
            trip.sudo().write({
                'state': 'closed',
                'returned_full_qty': max(0, trip.load_qty - delivered_bottles),
                'returned_empty_qty': sum(stops.mapped('empties_collected')),
            })
        self._h2o_on_closed()
        return True

    def action_cancel(self):
        """Cancel trips without deliveries; their orders go back to planning."""
        self._h2o_check_dispatcher()
        self._h2o_check_state(('planned', 'loaded', 'on_road'), self.env._("cancelled"))
        if self.stop_ids.filtered(lambda s: s.state == 'delivered'):
            raise UserError(self.env._("A trip with delivered stops cannot be cancelled; close it instead."))
        self.stop_ids.filtered(lambda s: s.state == 'pending')._h2o_set_skipped()
        self.write({'state': 'cancelled'})
        return True

    def action_reset_planned(self):
        """Plan a cancelled trip again; new stops can then be added to it."""
        self._h2o_check_dispatcher()
        self._h2o_check_state(('cancelled',), self.env._("reset to planned"))
        self.write({'state': 'planned'})
        return True

    def action_view_stops(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_dispatch.h2o_stop_action')
        action['domain'] = [('trip_id', '=', self.id)]
        action['context'] = {'default_trip_id': self.id}
        return action

    def _h2o_update_position(self, latitude, longitude):
        """Store the vehicle's last known position (sent by the driver app)."""
        self._h2o_check_driver()
        self.sudo().write({
            'last_latitude': latitude,
            'last_longitude': longitude,
            'last_position_at': fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Hooks for other modules (stock, billing, ...)
    # They run as the acting user, possibly a driver whose rights were
    # checked by the action; implementations use sudo() where they need it.
    # ------------------------------------------------------------------

    def _h2o_on_loaded(self):
        """Called after the trips were loaded."""

    def _h2o_on_started(self):
        """Called after the trips left the depot."""

    def _h2o_on_closed(self):
        """Called after the trips were closed."""

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    @api.model
    def _h2o_plan_day(self, date, routes=None):
        """Put the orders to deliver by ``date`` on the trips of that day.

        For each route (the given ones, else every route running on that
        weekday) the ``planned`` trip of the day is reused or created, and a
        stop is added for every confirmed order still to plan in the route's
        zones with a delivery date up to ``date``, ordered by zone then
        address. The orders become ``planned``.

        :return: the trips that got new stops
        """
        if routes is None:
            routes = self.env['h2o.route'].search([('company_id', 'in', self.env.companies.ids)])
            routes = routes.filtered(lambda r: r._h2o_runs_on(date))
        trips = self.browse()
        for route in routes:
            if not route.zone_ids:
                continue
            orders = self.env['sale.order'].search([
                ('state', '=', 'sale'),
                ('h2o_is_delivery', '=', True),
                ('h2o_delivery_state', '=', 'to_plan'),
                ('h2o_zone_id', 'in', route.zone_ids.ids),
                ('h2o_delivery_date', '<=', date),
                ('company_id', '=', route.company_id.id),
            ])
            if not orders:
                continue
            orders = orders.sorted(lambda o: (
                o.h2o_zone_id.sequence, o.h2o_zone_id.name,
                (o.partner_shipping_id.display_name or '').lower(), o.id,
            ))
            trip = self.search([
                ('route_id', '=', route.id), ('date', '=', date), ('state', '=', 'planned'),
            ], order='id', limit=1)
            if not trip:
                trip = self.create({'route_id': route.id, 'date': date, 'company_id': route.company_id.id})
            sequence = max(trip.stop_ids.mapped('sequence'), default=0)
            self.env['h2o.stop'].create([
                {'trip_id': trip.id, 'order_id': order.id, 'sequence': sequence + 10 * index}
                for index, order in enumerate(orders, start=1)
            ])
            trips |= trip
        return trips
