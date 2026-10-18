from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    h2o_subscription_lead_days = fields.Integer(related='company_id.h2o_subscription_lead_days', readonly=False)
