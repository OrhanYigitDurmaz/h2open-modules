from odoo.tests import new_test_user, tagged

from odoo.addons.h2o_dispatch.tests.common import H2oDispatchCase


@tagged('post_install', '-at_install')
class TestReportDelivery(H2oDispatchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cash_order = cls._order(cls.cash_customer, [(cls.water, 3), (cls.water_5l, 2)], empties=2)
        cls.account_order = cls._order(cls.account_customer, [(cls.water, 5)])

    def _rows(self, trip):
        self.env.flush_all()
        return self.env['h2o.report.delivery'].search([('trip_id', '=', trip.id)])

    def test_delivered_and_failed_stops(self):
        trip = self._started_trip()
        cash_stop = trip.stop_ids.filtered(lambda s: s.order_id == self.cash_order)
        account_stop = trip.stop_ids - cash_stop
        cash_stop.action_deliver({'empties_collected': 2, 'payment_method': 'cash', 'payment_amount': 120.0})
        account_stop.action_fail('not_home')

        rows = self._rows(trip)
        self.assertEqual(len(rows), 2)
        delivered = rows.filtered(lambda r: r.stop_id == cash_stop)
        self.assertRecordValues(delivered, [{
            'state': 'delivered',
            'partner_id': self.cash_customer.id,
            'zone_id': self.zone.id,
            'route_id': self.route.id,
            'driver_id': self.driver_a.id,
            'customer_type': 'home',
            'bottle_qty': 3.0,
            'packaged_qty': 2.0,
            'empties_collected': 2,
            'payment_method': 'cash',
            'payment_amount': 120.0,
            'delivered_count': 1,
            'success_rate': 100.0,
        }])
        failed = rows - delivered
        self.assertRecordValues(failed, [{
            'state': 'failed',
            'failure_reason': 'not_home',
            'bottle_qty': 0.0,
            'payment_amount': 0.0,
            'delivered_count': 0,
            'success_rate': 0.0,
        }])

        [(route, stops, delivered_stops, rate)] = self.env['h2o.report.delivery'].read_group(
            [('trip_id', '=', trip.id)], ['route_id'],
            ['stop_count:sum', 'delivered_count:sum', 'success_rate:avg'])
        self.assertEqual(route, self.route.id)
        self.assertEqual((stops, delivered_stops), (2, 1))
        self.assertAlmostEqual(rate, 50.0)

    def test_pending_stops_left_out_of_success_rate(self):
        trip = self._planned_trip()
        rows = self._rows(trip)
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows.mapped('state')), {'pending'})
        self.assertFalse(any(rows.mapped('success_rate')))

    def test_cancelled_trip_hidden(self):
        trip = self._planned_trip()
        trip.with_user(self.dispatcher).action_cancel()
        self.assertFalse(self._rows(trip))

    def test_access(self):
        trip = self._planned_trip()
        accountant = new_test_user(self.env, login='h2o_report_accountant', groups='h2o_base.group_h2o_accountant')
        self.env.flush_all()
        Report = self.env['h2o.report.delivery']
        self.assertEqual(Report.with_user(self.dispatcher).search_count([('trip_id', '=', trip.id)]), 2)
        self.assertEqual(Report.with_user(accountant).search_count([('trip_id', '=', trip.id)]), 2)
        self.assertFalse(Report.with_user(self.driver_a).has_access('read'))
