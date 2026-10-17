from odoo import fields, models


class H2oZone(models.Model):
    _inherit = 'h2o.zone'

    h2o_route_id = fields.Many2one(
        'h2o.route', string="Delivery Route", index=True, check_company=True,
        help="Route whose trips deliver this zone.",
    )
