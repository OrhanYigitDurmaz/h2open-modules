from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    h2o_order_cutoff_hour = fields.Float(related='company_id.h2o_order_cutoff_hour', readonly=False)
    h2o_app_token_days = fields.Integer(related='company_id.h2o_app_token_days', readonly=False)
