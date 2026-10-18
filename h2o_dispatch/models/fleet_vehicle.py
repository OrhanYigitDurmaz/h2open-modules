from odoo import fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    h2o_is_delivery_vehicle = fields.Boolean(
        string="Water Delivery Vehicle", index=True, tracking=True,
        help="The vehicle can be used for water delivery trips.",
    )
    h2o_capacity = fields.Integer(
        string="Capacity (bottles)", help="Number of 19 L bottles the vehicle can carry.",
    )
    h2o_driver_user_id = fields.Many2one(
        'res.users', string="Usual Driver", tracking=True,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('h2o_base.group_h2o_driver').ids)],
        help="Driver app user who usually drives this vehicle; proposed on its trips.",
    )
