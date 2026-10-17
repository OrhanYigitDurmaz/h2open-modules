from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class H2oTripPlan(models.TransientModel):
    _name = 'h2o.trip.plan'
    _description = 'Plan Delivery Trips'

    date = fields.Date(required=True, default=lambda self: fields.Date.context_today(self) + timedelta(days=1))
    route_ids = fields.Many2many(
        'h2o.route', string="Routes", compute='_compute_route_ids', store=True, readonly=False,
        help="Routes to plan. Defaults to the routes running on that day.",
    )

    @api.depends('date')
    def _compute_route_ids(self):
        routes = self.env['h2o.route'].search([('company_id', 'in', self.env.companies.ids)])
        for wizard in self:
            wizard.route_ids = routes.filtered(lambda r: wizard.date and r._h2o_runs_on(wizard.date))

    def action_plan(self):
        self.ensure_one()
        if not self.route_ids:
            raise UserError(self.env._("Select the routes to plan."))
        trips = self.env['h2o.trip']._h2o_plan_day(self.date, self.route_ids)
        if not trips:
            raise UserError(self.env._("There is nothing to plan on these routes for this day."))
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_dispatch.h2o_trip_action')
        action['domain'] = [('id', 'in', trips.ids)]
        action['context'] = {}
        if len(trips) == 1:
            action.update(view_mode='form', views=[(False, 'form')], res_id=trips.id)
        return action
