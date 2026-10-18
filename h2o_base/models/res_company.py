from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    h2o_order_cutoff_hour = fields.Float(
        string="Order Cut-off Hour",
        default=16.0,
        help="Orders taken after this hour (company time zone) are delivered on the next delivery day.",
    )
    h2o_app_access_hours = fields.Integer(
        string="App Access Token Validity (hours)",
        default=24,
        help="How long one mobile app access token works; the app then renews it on its own.",
    )
    h2o_app_refresh_days = fields.Integer(
        string="App Sign-in Validity (days)",
        default=90,
        help="A mobile app that is not used for this many days has to sign in again.",
    )
