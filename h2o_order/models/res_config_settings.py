from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    h2o_pricelist_home_id = fields.Many2one(related='company_id.h2o_pricelist_home_id', readonly=False)
    h2o_pricelist_office_id = fields.Many2one(related='company_id.h2o_pricelist_office_id', readonly=False)
    h2o_pricelist_reseller_id = fields.Many2one(related='company_id.h2o_pricelist_reseller_id', readonly=False)
