from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import H2oDispatchCase


@tagged('post_install', '-at_install')
class TestPlanning(H2oDispatchCase):

    def test_plan_day(self):
        late = self._order(self.account_customer, [(self.water, 3)], delivery_date=self.date - timedelta(days=3))
        today = self._order(self.cash_customer, [(self.water, 2), (self.water_5l, 1)], empties=2)
        future = self._order(self.cash_customer, [(self.water, 1)], delivery_date=self.date + timedelta(days=1))
        draft = self._order(self.cash_customer, [(self.water, 1)], confirm=False)

        trip = self.env['h2o.trip'].with_user(self.dispatcher)._h2o_plan_day(self.date)
        self.assertRecordValues(trip, [{
            'route_id': self.route.id, 'date': self.date, 'state': 'planned',
            'vehicle_id': self.van.id, 'driver_id': self.driver_a.id, 'stop_count': 2,
        }])
        self.assertTrue(trip.name.startswith('TRIP/'))
        # ordered by zone, then address
        self.assertEqual(trip.stop_ids.order_id.ids, [today.id, late.id])
        self.assertEqual((today | late).mapped('h2o_delivery_state'), ['planned', 'planned'])
        self.assertEqual(today.h2o_trip_id, trip)
        self.assertEqual((future | draft).mapped('h2o_delivery_state'), ['to_plan', 'to_plan'])

        stop = trip.stop_ids.filtered(lambda s: s.order_id == today)
        self.assertEqual(stop.partner_id, self.cash_customer)
        self.assertEqual(stop.payment_method, 'cash')
        self.assertEqual(stop.line_ids.mapped('qty_planned'), [2, 1])
        self.assertAlmostEqual(stop.amount_due, today.amount_total)
        self.assertEqual(trip.planned_bottle_qty, 5)
        self.assertEqual(trip.stop_ids.filtered(lambda s: s.order_id == late).payment_method, 'account')

        # planning again reuses the planned trip for the new orders only
        other = self._order(self.account_customer, [(self.water, 1)])
        self.assertEqual(self.env['h2o.trip']._h2o_plan_day(self.date), trip)
        self.assertEqual(trip.stop_count, 3)
        self.assertEqual(trip.stop_ids[-1].order_id, other)
        self.assertFalse(self.env['h2o.trip']._h2o_plan_day(self.date))

    def test_route_weekdays(self):
        self._order(self.cash_customer, [(self.water, 1)], delivery_date=self.date)
        tuesday = self.date + timedelta(days=1)
        self.assertFalse(self.env['h2o.trip']._h2o_plan_day(tuesday))
        # explicitly selected routes are planned on any day
        trip = self.env['h2o.trip']._h2o_plan_day(tuesday, self.route)
        self.assertEqual(trip.date, tuesday)

    def test_wizard(self):
        self._order(self.cash_customer, [(self.water, 1)])
        wizard_form = Form(self.env['h2o.trip.plan'].with_user(self.dispatcher))
        wizard_form.date = self.date
        self.assertIn(self.route, wizard_form.route_ids)
        action = wizard_form.save().action_plan()
        trip = self.env['h2o.trip'].browse(action['res_id'])
        self.assertEqual(trip.stop_count, 1)
        wizard = self.env['h2o.trip.plan'].with_user(self.dispatcher).create({'date': self.date})
        with self.assertRaises(UserError):
            wizard.action_plan()

    def test_manual_stops(self):
        order = self._order(self.cash_customer, [(self.water, 2)])
        trip = self.env['h2o.trip'].with_user(self.dispatcher).create({'route_id': self.route.id, 'date': self.date})
        self.assertEqual(trip.vehicle_id, self.van)
        trip.stop_ids = [(0, 0, {'order_id': order.id})]
        self.assertEqual(order.h2o_delivery_state, 'planned')
        self.assertEqual(trip.stop_ids.line_ids.product_id, self.water | self.deposit)
        trip.stop_ids.unlink()
        self.assertEqual(order.h2o_delivery_state, 'to_plan')

        trip = self._planned_trip()
        trip.with_user(self.dispatcher).unlink()
        self.assertEqual(order.h2o_delivery_state, 'to_plan')

    def test_cancel_order_removes_stop(self):
        order = self._order(self.cash_customer, [(self.water, 2)])
        trip = self._planned_trip()
        order._action_cancel()
        self.assertFalse(trip.stop_ids)
        self.assertEqual(order.h2o_delivery_state, 'cancelled')
