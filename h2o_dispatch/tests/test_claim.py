from unittest.mock import patch

from odoo.exceptions import AccessError, LockError, UserError
from odoo.tests import new_test_user, tagged

from .common import H2oDispatchCase


@tagged('post_install', '-at_install')
class TestClaim(H2oDispatchCase):
    """Drivers take open orders themselves; the day's planning keeps working beside it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = cls.driver_a._h2o_today()
        cls.order_1 = cls._order(cls.cash_customer, [(cls.water, 2)], delivery_date=cls.today)
        cls.order_2 = cls._order(cls.account_customer, [(cls.water, 1)], delivery_date=cls.today)

    def test_claim_creates_trip_then_reuses_it(self):
        stop = self.order_1.with_user(self.driver_a)._h2o_claim()
        trip = stop.trip_id
        self.assertTrue(stop.claimed)
        self.assertEqual(self.order_1.h2o_delivery_state, 'planned')
        self.assertEqual((trip.date, trip.driver_id, trip.state), (self.today, self.driver_a, 'planned'))
        # driver A drives the test route's van: the trip is on that route, with that van
        self.assertEqual((trip.route_id, trip.vehicle_id), (self.route, self.van))

        stop_2 = self.order_2.with_user(self.driver_a)._h2o_claim()
        self.assertEqual(stop_2.trip_id, trip)
        self.assertGreater(stop_2.sequence, stop.sequence)

    def test_claim_goes_on_the_trip_on_the_road(self):
        planned = self.env['h2o.trip'].create({
            'date': self.today, 'driver_id': self.driver_b.id, 'vehicle_id': self.van_b.id})
        on_road = self.env['h2o.trip'].create({
            'date': self.today, 'driver_id': self.driver_b.id, 'vehicle_id': self.van_b.id})
        on_road.action_start()
        stop = self.order_1.with_user(self.driver_b)._h2o_claim()
        self.assertEqual(stop.trip_id, on_road)
        self.assertFalse(planned.stop_ids)
        # driver B has no route and no usual vehicle of their own
        other = self.env['h2o.trip']._h2o_trip_for_driver(self.driver_b, self.date, self.env.company)
        self.assertFalse(other.route_id or other.vehicle_id)

    def test_taken_order_cannot_be_claimed_again(self):
        self.order_1.with_user(self.driver_a)._h2o_claim()
        with self.assertRaisesRegex(UserError, 'already taken'):
            self.order_1.with_user(self.driver_b)._h2o_claim()
        accountant = new_test_user(self.env, login='h2o_claim_accountant', groups='h2o_base.group_h2o_accountant')
        with self.assertRaises(AccessError):
            self.order_2.with_user(accountant)._h2o_claim()

    def test_claim_while_another_driver_holds_the_lock(self):
        with patch.object(type(self.env['sale.order']), 'lock_for_update', side_effect=LockError("locked")), \
                self.assertRaisesRegex(UserError, 'right now'):
            self.order_1.with_user(self.driver_b)._h2o_claim()
        self.assertEqual(self.order_1.h2o_delivery_state, 'to_plan')

    def test_release(self):
        stop = self.order_1.with_user(self.driver_a)._h2o_claim()
        trip = stop.trip_id
        trip.action_start()
        self.assertEqual(stop.with_user(self.driver_a).action_release(), self.order_1)
        self.assertFalse(stop.exists())
        self.assertEqual(self.order_1.h2o_delivery_state, 'to_plan')
        self.assertFalse(trip.stop_ids)

    def test_release_only_own_claims(self):
        stop = self.order_2.with_user(self.driver_a)._h2o_claim()
        with self.assertRaises(AccessError):
            stop.with_user(self.driver_b).action_release()
        planned_stop = self.env['h2o.trip']._h2o_plan_day(self.today, self.route).stop_ids - stop
        self.assertEqual(planned_stop.order_id, self.order_1)
        with self.assertRaisesRegex(UserError, 'took yourself'):
            planned_stop.with_user(self.driver_a).action_release()

    def test_planning_skips_claimed_orders(self):
        self.order_1.with_user(self.driver_a)._h2o_claim()
        trip = self.env['h2o.trip']._h2o_plan_day(self.today, self.route)
        # the planned trip of driver A on the route is the one the claim created
        self.assertEqual(trip.stop_ids.order_id, self.order_1 | self.order_2)
        self.assertEqual(len(trip), 1)
