from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    h2o_cash_journal_id = fields.Many2one(related='company_id.h2o_cash_journal_id', readonly=False)
    h2o_card_journal_id = fields.Many2one(related='company_id.h2o_card_journal_id', readonly=False)
