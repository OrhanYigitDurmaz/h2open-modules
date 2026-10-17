from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import H2oDispatchCase


@tagged('post_install', '-at_install')
class TestTrip(H2oDispatchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order_1 = cls._order(cls.cash_customer, [(cls.water, 3)], empties=3)
        cls.order_2 = cls._order(cls.account_customer, [(cls.water, 4)], empties=2)

    def test_trip_flow(self):
        trip = self._planned_trip().with_user(self.driver_a)
        registry_trip = self.env.registry['h2o.trip']
        with patch.object(registry_trip, '_h2o_on_loaded', autospec=True) as loaded:
            trip.action_load()
        loaded.assert_called_once()
        self.assertEqual(trip.state, 'loaded')
        self.assertEqual(trip.load_qty, 7)

        with patch.object(registry_trip, '_h2o_on_started', autospec=True) as started:
            trip.action_start()
        started.assert_called_once()
        self.assertEqual(trip.state, 'on_road')

        stop_1, stop_2 = trip.stop_ids
        stop_1.action_deliver({'empties_collected': 2})
        with self.assertRaises(UserError):
            trip.action_close()
        stop_2.action_fail('refused')

        with patch.object(registry_trip, '_h2o_on_closed', autospec=True) as closed:
            trip.action_close()
        closed.assert_called_once()
        self.assertRecordValues(trip, [{
            'state': 'closed', 'delivered_count': 1, 'failed_count': 1,
            'returned_full_qty': 4, 'returned_empty_qty': 2,
        }])
        with self.assertRaises(UserError):
            trip.action_start()

    def test_start_loads_planned_trip(self):
        trip = self._planned_trip()
        with patch.object(self.env.registry['h2o.trip'], '_h2o_on_loaded', autospec=True) as loaded:
            trip.with_user(self.driver_a).action_start()
        loaded.assert_called_once()
        self.assertEqual(trip.state, 'on_road')
        self.assertEqual(trip.load_qty, 7)

    def test_load_needs_driver_and_vehicle(self):
        trip = self._planned_trip()
        trip.vehicle_id = False
        with self.assertRaises(UserError):
            trip.action_load()

    def test_cancel_and_reset(self):
        trip = self._started_trip()
        with self.assertRaises(AccessError):
            trip.with_user(self.driver_a).action_cancel()
        trip.with_user(self.dispatcher).action_cancel()
        self.assertEqual(trip.state, 'cancelled')
        self.assertEqual(trip.stop_ids.mapped('state'), ['skipped', 'skipped'])
        self.assertEqual((self.order_1 | self.order_2).mapped('h2o_delivery_state'), ['to_plan', 'to_plan'])

        trip.with_user(self.dispatcher).action_reset_planned()
        self.assertEqual(trip.state, 'planned')
        self.assertEqual(self._planned_trip(), trip)
        self.assertEqual(trip.pending_count, 2)

    def test_cancel_refused_after_delivery(self):
        trip = self._started_trip()
        trip.stop_ids[0].action_deliver()
        with self.assertRaises(UserError):
            trip.action_cancel()
        with self.assertRaises(UserError):
            trip.stop_ids[0].unlink()

    def test_position(self):
        trip = self._started_trip()
        trip.with_user(self.driver_a)._h2o_update_position(39.92, 32.85)
        self.assertAlmostEqual(trip.last_latitude, 39.92)
        self.assertTrue(trip.last_position_at)
