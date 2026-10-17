from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import tagged

from .common import H2oBillingCase


@tagged('post_install', '-at_install')
class TestMonthlyStatement(H2oBillingCase):

    def _deliver_all(self, orders, day=None):
        trip = self._started_trip(day)
        for order in orders:
            self._deliver(trip, order)
        return trip

    def test_statement_groups_orders(self):
        order_1 = self._order(self.account_customer, water_qty=2)
        order_2 = self._order(self.account_customer, water_qty=1, empties=1)
        other_month = self._order(self.account_customer, delivery_date=self.date + timedelta(days=28))
        self._deliver_all(order_1 + order_2)
        self.assertFalse((order_1 + order_2).invoice_ids)

        wizard = self.env['h2o.statement.wizard'].with_user(self.accountant).create({'month': self.date})
        action = wizard.action_create_statements()
        invoice = self.env['account.move'].search(action['domain'])
        self.assertRecordValues(invoice, [{
            'state': 'posted', 'partner_id': self.account_customer.id,
            'h2o_statement_month': self.date.replace(day=1), 'h2o_stop_id': False,
        }])
        self.assertEqual(invoice.invoice_line_ids.sale_line_ids.order_id, order_1 + order_2)
        self.assertEqual(len(invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'line_section')), 2)
        self.assertAlmostEqual(invoice.amount_total, order_1.amount_total + order_2.amount_total)
        self.assertEqual((order_1 + order_2).mapped('invoice_status'), ['invoiced', 'invoiced'])
        self.assertFalse(other_month.invoice_ids)

        # a second run has nothing left to invoice
        action = wizard.action_create_statements()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertFalse(self.env['sale.order']._h2o_create_monthly_statements(self.date))
        self.assertEqual((order_1 + order_2).invoice_ids, invoice)

    def test_statement_skips_cash_customers_and_other_partners(self):
        cash_order = self._order(self.cash_customer)
        account_order = self._order(self.account_customer)
        other_customer = self.account_customer.copy({'name': 'Other Account Customer'})
        other_order = self._order(other_customer)
        self._deliver_all(cash_order + account_order + other_order)

        invoices = self.env['sale.order']._h2o_create_monthly_statements(self.date, other_customer)
        self.assertEqual(invoices.partner_id, other_customer)
        self.assertFalse(account_order.invoice_ids)
        self.assertEqual(len(cash_order.invoice_ids), 1, "only the delivery invoice")

    def test_cron_invoices_previous_month(self):
        first = fields.Date.context_today(self.env.user).replace(day=1) - relativedelta(months=1)
        monday = first + timedelta(days=-first.weekday() % 7)
        order = self._order(self.account_customer, delivery_date=monday)
        self._deliver_all(order, monday)

        self.env['account.move'].sudo()._cron_h2o_monthly_invoices()  # as the cron user
        self.assertRecordValues(order.invoice_ids, [{'state': 'posted', 'h2o_statement_month': first}])
