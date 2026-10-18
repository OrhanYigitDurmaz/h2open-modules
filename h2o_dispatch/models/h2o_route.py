from odoo import api, fields, models


class H2oRoute(models.Model):
    _name = 'h2o.route'
    _description = 'Delivery Route'
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    zone_ids = fields.One2many('h2o.zone', 'h2o_route_id', string="Zones", check_company=True)
    weekday_ids = fields.Many2many(
        'h2o.weekday', string="Running Days",
        help="Days the route runs. Leave empty to run every day.",
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string="Vehicle", check_company=True,
        domain="[('h2o_is_delivery_vehicle', '=', True)]",
    )
    driver_id = fields.Many2one(
        'res.users', string="Driver",
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('h2o_base.group_h2o_driver').ids)],
        help="Driver of the route's trips. Defaults to the usual driver of the vehicle.",
    )
    trip_ids = fields.One2many('h2o.trip', 'route_id', string="Trips")
    trip_count = fields.Integer(compute='_compute_trip_count')
    color = fields.Integer()
    note = fields.Text()

    _code_company_unique = models.Constraint(
        'UNIQUE(code, company_id)', 'The route code must be unique per company.',
    )

    @api.depends('trip_ids')
    def _compute_trip_count(self):
        counts = dict(self.env['h2o.trip']._read_group(
            [('route_id', 'in', self.ids)], ['route_id'], ['__count'],
        ))
        for route in self:
            route.trip_count = counts.get(route, 0)

    def _h2o_runs_on(self, date):
        """Whether the route runs on ``date``."""
        self.ensure_one()
        return not self.weekday_ids or date.weekday() in self.weekday_ids.mapped('code')

    def _h2o_driver(self):
        """Driver of the route's trips: the route's own, else the vehicle's usual driver."""
        self.ensure_one()
        return self.driver_id or self.vehicle_id.h2o_driver_user_id

    def action_view_trips(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_dispatch.h2o_trip_action')
        action['domain'] = [('route_id', '=', self.id)]
        action['context'] = {'default_route_id': self.id}
        return action
