from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    h2o_deposit_account_id = fields.Many2one(related='company_id.h2o_deposit_account_id', readonly=False)
