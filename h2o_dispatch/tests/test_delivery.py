from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import H2oDispatchCase


@tagged('post_install', '-at_install')
class TestDelivery(H2oDispatchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 3 bottles, 1 empty back: 2 deposits
        cls.order = cls._order(cls.cash_customer, [(cls.water, 3), (cls.water_5l, 2)], empties=1)

    def _stop(self, trip):
        return trip.stop_ids.filtered(lambda s: s.order_id == self.order)

    def _ledger(self):
        return self.env['h2o.container.move'].search([('partner_id', '=', self.cash_customer.id)])

    def test_stop_shows_empties_expected(self):
        """Drivers have no rights on sales orders but still see the empties to collect."""
        stop = self._stop(self._planned_trip()).with_user(self.driver_a)
        self.assertEqual(stop.empties_expected, 1)
        self.order.h2o_empties_expected = 3
        self.assertEqual(stop.empties_expected, 3)

    def test_deliver_as_planned(self):
        trip = self._started_trip()
        stop = self._stop(trip).with_user(self.driver_a)
        with patch.object(self.env.registry['h2o.stop'], '_h2o_on_delivered', autospec=True) as hook:
            stop.action_deliver({'signature': 'aGVsbG8=', 'latitude': 39.9, 'longitude': 32.8})
        hook.assert_called_once()

        self.assertEqual(stop.state, 'delivered')
        self.assertTrue(stop.done_at)
        self.assertEqual(stop.empties_collected, 1)
        self.assertEqual(stop.payment_method, 'cash')
        self.assertAlmostEqual(stop.amount_due, self.order.amount_total)
        self.assertAlmostEqual(stop.payment_amount, self.order.amount_total)
        self.assertAlmostEqual(trip.cash_expected, self.order.amount_total)
        self.assertEqual(self.order.h2o_delivery_state, 'delivered')
        delivered = {line.product_id: line.qty_delivered for line in self.order.order_line}
        self.assertEqual(delivered, {self.water: 3, self.water_5l: 2, self.deposit: 2})
        self.assertRecordValues(self._ledger(), [{
            'product_id': self.bottle.id, 'qty_out': 3, 'qty_in': 1, 'deposit_amount': 500.0,
            'source': 'delivery', 'state': 'done', 'origin': self.order.name,
        }])
        self.assertEqual(self.cash_customer.h2o_bottle_balance, 2)

        with self.assertRaises(UserError):
            stop.action_deliver()

    def test_deliver_partial(self):
        trip = self._started_trip()
        stop = self._stop(trip).with_user(self.driver_a)
        stop.action_deliver({
            'lines': [{'product_id': self.water.id, 'qty_delivered': 2}],
            'empties_collected': 2,
            'payment_method': 'card',
            'note': 'Only two needed',
        })
        delivered = {line.product_id: line.qty_delivered for line in self.order.order_line}
        self.assertEqual(delivered, {self.water: 2, self.water_5l: 2, self.deposit: 0})
        self.assertRecordValues(self._ledger(), [{'qty_out': 2, 'qty_in': 2, 'deposit_amount': 0.0}])
        self.assertLess(stop.amount_due, self.order.amount_total)
        self.assertAlmostEqual(stop.payment_amount, stop.amount_due)
        self.assertFalse(trip.cash_expected, "card payments are not cash")

    def test_deliver_account_customer(self):
        order = self._order(self.account_customer, [(self.water, 1)], empties=1)
        trip = self._started_trip()
        stop = trip.stop_ids.filtered(lambda s: s.order_id == order).with_user(self.driver_a)
        stop.action_deliver()
        self.assertEqual(stop.payment_method, 'account')
        self.assertFalse(stop.payment_amount)
        self.assertTrue(stop.amount_due)

    def test_deliver_bad_values(self):
        trip = self._started_trip()
        stop = self._stop(trip).with_user(self.driver_a)
        with self.assertRaises(UserError):
            stop.action_deliver({'lines': [{'product_id': self.bottle.id, 'qty_delivered': 1}]})
        with self.assertRaises(UserError):
            stop.action_deliver({'lines': [{'product_id': self.water.id, 'qty_delivered': -1}]})
        with self.assertRaises(UserError):
            stop.action_deliver({'empties_collected': -1})
        with self.assertRaises(UserError):
            stop.action_deliver({'state': 'delivered'})
        self.assertEqual(stop.state, 'pending')

    def test_deliver_needs_started_trip(self):
        trip = self._planned_trip()
        with self.assertRaises(UserError):
            self._stop(trip).with_user(self.driver_a).action_deliver()

    def test_fail_replans(self):
        trip = self._started_trip()
        stop = self._stop(trip).with_user(self.driver_a)
        with self.assertRaises(UserError):
            stop.action_fail('lost')
        with patch.object(self.env.registry['h2o.stop'], '_h2o_on_failed', autospec=True) as hook:
            stop.action_fail('not_home', 'Rang twice')
        hook.assert_called_once()
        self.assertRecordValues(stop, [{
            'state': 'failed', 'failure_reason': 'not_home', 'failure_note': 'Rang twice', 'amount_due': 0.0,
        }])
        self.assertEqual(self.order.h2o_delivery_state, 'to_plan')
        self.assertEqual(trip.failed_count, 1)
        self.assertFalse(self._ledger())
        self.assertFalse(any(self.order.order_line.mapped('qty_delivered')))

        # planned again on a new trip, the one on the road is left alone
        new_trip = self._planned_trip()
        self.assertNotEqual(new_trip, trip)
        self.assertEqual(new_trip.stop_ids.order_id, self.order)
        self.assertEqual(self.order.h2o_trip_id, new_trip)
        self.assertEqual(self.order.h2o_delivery_state, 'planned')

    def test_skip_replans(self):
        trip = self._started_trip()
        stop = self._stop(trip).with_user(self.driver_a)
        stop.action_skip()
        self.assertEqual(stop.state, 'skipped')
        self.assertEqual(self.order.h2o_delivery_state, 'to_plan')
        self.assertEqual(trip.failed_count, 1)
