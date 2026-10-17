from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    h2o_order_cutoff_hour = fields.Float(
        string="Order Cut-off Hour",
        default=16.0,
        help="Orders taken after this hour (company time zone) are delivered on the next delivery day.",
    )
    h2o_app_token_days = fields.Integer(
        string="App Login Validity (days)",
        default=30,
        help="How long a mobile app login stays valid before the user has to sign in again.",
    )
