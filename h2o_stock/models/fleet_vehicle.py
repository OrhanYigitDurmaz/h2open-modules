from odoo import api, fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    h2o_warehouse_id = fields.Many2one(
        'stock.warehouse', string="Depot",
        default=lambda self: self.env['stock.warehouse']._h2o_default_for(self.env.company),
        help="Warehouse the vehicle is based at; its stock location is created under it.",
    )
    h2o_location_id = fields.Many2one(
        'stock.location', string="Vehicle Location", readonly=True, copy=False,
        help="Internal location holding what the vehicle carries.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        vehicles = super().create(vals_list)
        vehicles._h2o_ensure_location()
        return vehicles

    def write(self, vals):
        res = super().write(vals)
        if {'h2o_is_delivery_vehicle', 'h2o_warehouse_id', 'license_plate', 'model_id'} & set(vals):
            self._h2o_ensure_location()
        return res

    def _h2o_ensure_location(self):
        """Create or update the stock location of the delivery vehicles,
        "WH/Vehicles/<license plate>", under their depot warehouse."""
        for vehicle in self.sudo().filtered('h2o_is_delivery_vehicle'):
            warehouse = vehicle.h2o_warehouse_id or self.env['stock.warehouse']._h2o_default_for(
                vehicle.company_id or self.env.company)
            if not warehouse:
                continue
            vals = {
                'name': vehicle.license_plate or vehicle.name,
                'location_id': warehouse._h2o_vehicles_location().id,
                'company_id': warehouse.company_id.id,
            }
            location = vehicle.h2o_location_id
            if not location:
                location = self.env['stock.location'].sudo().create(dict(
                    vals, usage='internal', h2o_vehicle_id=vehicle.id,
                ))
                vehicle.write({'h2o_location_id': location.id, 'h2o_warehouse_id': warehouse.id})
            elif (location.name, location.location_id.id, location.company_id.id) != tuple(vals.values()):
                location.write(vals)

    @api.model
    def _h2o_create_missing_locations(self):
        """Give a stock location to the existing delivery vehicles (on install)."""
        self.with_context(active_test=False).search([
            ('h2o_is_delivery_vehicle', '=', True), ('h2o_location_id', '=', False),
        ])._h2o_ensure_location()

    def _h2o_stock_location(self):
        """The vehicle's stock location, created if missing."""
        self.ensure_one()
        if not self.h2o_location_id:
            self._h2o_ensure_location()
        return self.h2o_location_id
