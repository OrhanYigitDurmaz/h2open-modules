from odoo import api, fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    h2o_vehicle_location_id = fields.Many2one(
        'stock.location', string="Vehicles Location", readonly=True, copy=False,
        help="Parent location of the delivery vehicles based at this warehouse.",
    )

    @api.model
    def _h2o_default_for(self, company):
        """The company's main warehouse (the default depot of routes and vehicles)."""
        return self.sudo().search([('company_id', '=', company.id)], limit=1).with_env(self.env)

    def _h2o_vehicles_location(self):
        """The "WH/Vehicles" location under the warehouse, created on first use.
        It is internal (not a view) so the vehicles are named "WH/Vehicles/<plate>"."""
        self.ensure_one()
        if not self.h2o_vehicle_location_id:
            self.sudo().h2o_vehicle_location_id = self.env['stock.location'].sudo().create({
                'name': self.env._("Vehicles"),
                'usage': 'internal',
                'location_id': self.view_location_id.id,
                'company_id': self.company_id.id,
            })
        return self.h2o_vehicle_location_id

    @api.model
    def _h2o_activate_internal_types(self):
        """Vehicles are internal locations: show the internal transfers (on install)."""
        self.search([]).int_type_id.active = True
