from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    h2o_deposit_account_id = fields.Many2one(
        'account.account', string="Bottle Deposit Account", check_company=True,
        domain="[('account_type', 'in', ('liability_current', 'liability_non_current'))]",
        help="Liability account credited when a bottle deposit is invoiced, and debited when it is refunded.",
    )
