from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    h2o_cash_journal_id = fields.Many2one(
        'account.journal', string="Driver Cash Journal", check_company=True,
        domain="[('type', '=', 'cash')]",
        help="Journal of the cash collected by drivers on delivery. Defaults to the first cash journal, "
             "created when the company has none.",
    )
    h2o_card_journal_id = fields.Many2one(
        'account.journal', string="Card Payment Journal", check_company=True,
        domain="[('type', 'in', ('bank', 'credit'))]",
        help="Journal of the card payments taken on delivery. Defaults to the first bank journal.",
    )

    def _h2o_payment_journal(self, method):
        """Journal for a payment collected on delivery with ``method``
        (``cash`` or ``card``): the configured one, else the first cash or
        bank journal of the company. A driver cash journal is created when
        the company has no cash journal at all."""
        self.ensure_one()
        Journal = self.env['account.journal']
        domain = Journal._check_company_domain(self)
        if method == 'cash':
            return (
                self.h2o_cash_journal_id
                or Journal.search([*domain, ('type', '=', 'cash')], limit=1)
                or self.sudo()._h2o_create_cash_journal()
            )
        return self.h2o_card_journal_id or Journal.search([*domain, ('type', '=', 'bank')], limit=1)

    def _h2o_create_cash_journal(self):
        self.ensure_one()
        if not self.chart_template:
            return self.env['account.journal']
        journal = self.env['account.journal'].create({
            'name': self.env._("Driver Cash"),
            'type': 'cash',
            'code': 'DCSH',
            'company_id': self.id,
        })
        self.h2o_cash_journal_id = journal
        return journal
