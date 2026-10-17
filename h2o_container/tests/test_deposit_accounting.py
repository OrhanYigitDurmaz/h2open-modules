from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestDepositAccounting(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.deposit_account = cls.env['account.account'].create({
            'name': 'Bottle deposits', 'code': '329950', 'account_type': 'liability_current',
        })
        cls.env.company.h2o_deposit_account_id = cls.deposit_account
        cls.deposit = cls.env.ref('h2o_container.product_deposit_19l')
        cls.water = cls.env.ref('h2o_container.product_water_19l')

    def _invoice(self, move_type):
        return self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [
                Command.create({'product_id': self.water.id, 'quantity': 2, 'price_unit': 120.0}),
                Command.create({'product_id': self.deposit.id, 'quantity': 2, 'price_unit': 250.0}),
            ],
        })

    def test_deposit_on_liability_account(self):
        for move_type in ('out_invoice', 'out_refund'):
            invoice = self._invoice(move_type)
            water_line, deposit_line = invoice.invoice_line_ids
            self.assertEqual(deposit_line.account_id, self.deposit_account)
            self.assertNotEqual(water_line.account_id, self.deposit_account)
            invoice.action_post()
            self.assertEqual(deposit_line.account_id, self.deposit_account)

    def test_vendor_bill_untouched(self):
        bill = self._invoice('in_invoice')
        self.assertNotEqual(bill.invoice_line_ids[1].account_id, self.deposit_account)

    def test_without_setting_income_account_is_kept(self):
        self.env.company.h2o_deposit_account_id = False
        invoice = self._invoice('out_invoice')
        self.assertEqual(invoice.invoice_line_ids[1].account_id.account_type, 'income')
