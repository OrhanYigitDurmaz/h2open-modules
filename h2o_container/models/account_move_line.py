from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _compute_account_id(self):
        """Book customer invoice lines of deposit products on the company's
        deposit liability account instead of an income account."""
        super()._compute_account_id()
        for line in self:
            account = line.company_id.h2o_deposit_account_id
            if (
                account
                and line.display_type == 'product'
                and line.product_id.h2o_product_kind == 'deposit'
                and line.move_id.is_sale_document(include_receipts=True)
            ):
                line.account_id = account
