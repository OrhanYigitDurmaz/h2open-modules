from odoo import fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    h2o_vehicle_id = fields.Many2one(
        'fleet.vehicle', string="Delivery Vehicle", readonly=True, copy=False, index='btree_not_null',
        help="The delivery vehicle whose load this location holds.",
    )
