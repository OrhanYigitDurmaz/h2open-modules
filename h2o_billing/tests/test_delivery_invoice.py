from unittest.mock import patch

from odoo.tests import tagged

from .common import H2oBillingCase


@tagged('post_install', '-at_install')
class TestDeliveryInvoice(H2oBillingCase):

    def _payments(self, invoice):
        return invoice.matched_payment_ids

    def test_cash_delivery_paid(self):
        order = self._order(self.cash_customer, water_qty=2)
        trip = self._started_trip()
        stop = self._deliver(trip, order)

        self.assertEqual(stop.state, 'delivered')
        invoice = stop.invoice_ids
        self.assertEqual(len(invoice), 1)
        self.assertRecordValues(invoice, [{
            'state': 'posted', 'move_type': 'out_invoice', 'partner_id': self.cash_customer.id,
            'currency_id': self.env.ref('base.TRY').id, 'h2o_stop_id': stop.id,
            'payment_state': invoice._get_invoice_in_payment_state(), 'amount_residual': 0.0,
        }])
        self.assertAlmostEqual(invoice.amount_total, stop.amount_due)
        self.assertAlmostEqual(invoice.amount_total, order.amount_total)
        self.assertEqual(self._payments(invoice).journal_id, self.cash_journal)
        self.assertEqual(order.invoice_ids, invoice)
        self.assertEqual(order.invoice_status, 'invoiced')
        for line in order.order_line:
            self.assertEqual(line.qty_invoiced, line.qty_delivered)

    def test_deposit_line_on_liability_account(self):
        order = self._order(self.cash_customer, water_qty=3, empties=1)
        stop = self._deliver(self._started_trip(), order)
        deposit_line = stop.invoice_ids.invoice_line_ids.filtered(lambda l: l.product_id == self.deposit)
        self.assertRecordValues(deposit_line, [{'quantity': 2, 'account_id': self.deposit_account.id}])
        water_line = stop.invoice_ids.invoice_line_ids.filtered(lambda l: l.product_id == self.water)
        self.assertEqual(water_line.account_id.account_type, 'income')

    def test_card_partial_payment(self):
        order = self._order(self.card_customer, water_qty=2)
        stop = self._deliver(self._started_trip(), order, {'payment_amount': 100.0})
        invoice = stop.invoice_ids
        self.assertEqual(stop.payment_method, 'card')
        self.assertEqual(invoice.payment_state, 'partial')
        self.assertAlmostEqual(invoice.amount_residual, invoice.amount_total - 100.0)
        self.assertEqual(self._payments(invoice).journal_id, self.card_journal)

    def test_partial_delivery_invoices_delivered_quantities(self):
        order = self._order(self.cash_customer, water_qty=3)
        stop = self._deliver(self._started_trip(), order, {
            'lines': [{'product_id': self.water.id, 'qty_delivered': 1}], 'empties_collected': 0,
        })
        lines = stop.invoice_ids.invoice_line_ids
        self.assertEqual(
            {line.product_id: line.quantity for line in lines}, {self.water: 1, self.deposit: 1},
        )
        self.assertAlmostEqual(stop.invoice_ids.amount_total, stop.amount_due)
        self.assertEqual(stop.invoice_ids.payment_state, stop.invoice_ids._get_invoice_in_payment_state())

    def test_no_payment_leaves_invoice_open(self):
        order = self._order(self.cash_customer, water_qty=2)
        stop = self._deliver(self._started_trip(), order, {'payment_method': 'none'})
        invoice = stop.invoice_ids
        self.assertRecordValues(invoice, [{'state': 'posted', 'payment_state': 'not_paid'}])
        self.assertAlmostEqual(invoice.amount_residual, invoice.amount_total)
        self.assertFalse(self._payments(invoice))

    def test_account_customer_not_invoiced_on_delivery(self):
        order = self._order(self.account_customer)
        stop = self._deliver(self._started_trip(), order)
        self.assertEqual(stop.state, 'delivered')
        self.assertFalse(stop.invoice_ids)
        self.assertFalse(order.invoice_ids)
        self.assertEqual(order.invoice_status, 'to invoice')

    def test_invoice_failure_keeps_delivery(self):
        order = self._order(self.cash_customer)
        trip = self._started_trip()
        no_journal = self.env['account.journal']
        with patch.object(self.env.registry['res.company'], '_h2o_payment_journal', return_value=no_journal), \
                self.assertLogs('odoo.addons.h2o_billing.models.h2o_stop', level='WARNING'):
            stop = self._deliver(trip, order)
        self.assertEqual(stop.state, 'delivered')
        self.assertEqual(order.h2o_delivery_state, 'delivered')
        self.assertFalse(order.invoice_ids, "the invoice is rolled back with the failed payment")
        self.assertIn('could not be created', order.message_ids[0].body)

    def test_default_payment_journals(self):
        self.company.write({'h2o_cash_journal_id': False, 'h2o_card_journal_id': False})
        cash = self.company._h2o_payment_journal('cash')
        card = self.company._h2o_payment_journal('card')
        self.assertEqual((cash.type, cash.company_id), ('cash', self.company))
        self.assertEqual((card.type, card.company_id), ('bank', self.company))

        # a company without any cash journal gets one for its drivers
        self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'cash')]).action_archive()
        driver_cash = self.company._h2o_payment_journal('cash')
        self.assertRecordValues(driver_cash, [{'type': 'cash', 'code': 'DCSH', 'company_id': self.company.id}])
        self.assertEqual(self.company.h2o_cash_journal_id, driver_cash)
