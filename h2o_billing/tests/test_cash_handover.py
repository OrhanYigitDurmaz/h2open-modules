from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import H2oBillingCase


@tagged('post_install', '-at_install')
class TestCashHandover(H2oBillingCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cash_order = cls._order(cls.cash_customer, water_qty=2)
        cls.card_order = cls._order(cls.card_customer, water_qty=1, empties=1)

    def _closed_trip(self):
        trip = self._started_trip()
        self._deliver(trip, self.cash_order)
        self._deliver(trip, self.card_order)
        trip.with_user(self.driver).action_close()
        return trip

    def test_handover_created_on_close(self):
        trip = self._closed_trip()
        handover = trip.h2o_cash_handover_ids
        self.assertEqual(len(handover), 1)
        self.assertRecordValues(handover, [{
            'state': 'draft', 'driver_id': self.driver.id, 'expected': trip.cash_expected,
        }])
        self.assertAlmostEqual(handover.expected, self.cash_order.amount_total, msg="card payments are not cash")
        self.assertTrue(handover.name.startswith('CASH/'))

    def test_approve(self):
        trip = self._closed_trip()
        handover = trip.h2o_cash_handover_ids.with_user(self.accountant)
        handover.counted = handover.expected - 10.0
        self.assertAlmostEqual(handover.difference, -10.0)
        handover.action_approve()
        self.assertRecordValues(handover, [{'state': 'approved', 'approved_by': self.accountant.id}])
        self.assertAlmostEqual(trip.cash_handed_in, handover.expected - 10.0)

        handover.action_draft()
        self.assertEqual(handover.state, 'draft')
        self.assertFalse(trip.cash_handed_in)

    def test_one_per_trip(self):
        trip = self._closed_trip()
        self.assertFalse(trip._h2o_create_cash_handovers(), "the trip already has its handover")
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self.env['h2o.cash.handover'].create({'trip_id': trip.id})

    def test_access(self):
        trip = self._closed_trip()
        handover = trip.h2o_cash_handover_ids
        # the driver reads their own handovers only, and cannot approve them
        self.assertEqual(self.env['h2o.cash.handover'].with_user(self.driver).search([]), handover)
        self.assertFalse(self.env['h2o.cash.handover'].with_user(self.driver_b).search([]))
        with self.assertRaises(AccessError):
            handover.with_user(self.driver).action_approve()
        with self.assertRaises(AccessError):
            handover.with_user(self.driver).counted = 1.0
        # accountants count and approve, managers delete
        with self.assertRaises(AccessError):
            handover.with_user(self.accountant).unlink()
        handover.unlink()
