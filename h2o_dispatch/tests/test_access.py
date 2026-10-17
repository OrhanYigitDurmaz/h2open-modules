from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import H2oDispatchCase


@tagged('post_install', '-at_install')
class TestDispatchAccess(H2oDispatchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls._order(cls.cash_customer, [(cls.water, 2)])
        cls.trip = cls.env['h2o.trip']._h2o_plan_day(cls.date, cls.route)
        cls.trip.action_start()
        cls.stop = cls.trip.stop_ids
        cls.trip_b = cls.env['h2o.trip'].create({
            'date': cls.date, 'vehicle_id': cls.van_b.id, 'driver_id': cls.driver_b.id,
        })

    def test_driver_sees_own_trips_only(self):
        Trip = self.env['h2o.trip'].with_user(self.driver_a)
        self.assertEqual(Trip.search([]), self.trip)
        self.assertEqual(self.env['h2o.stop'].with_user(self.driver_a).search([]), self.stop)
        self.assertEqual(self.env['h2o.stop'].with_user(self.driver_b).search([]), self.env['h2o.stop'])
        with self.assertRaises(AccessError):
            self.trip.with_user(self.driver_b).read(['name'])
        with self.assertRaises(AccessError):
            self.stop.with_user(self.driver_b).read(['state'])
        with self.assertRaises(AccessError):
            self.stop.line_ids.with_user(self.driver_b).read(['qty_planned'])
        # the driver reads the delivery vans, not the other vehicles
        self.assertTrue(self.van.with_user(self.driver_b).name)

    def test_driver_cannot_act_on_other_trip(self):
        with self.assertRaises(AccessError):
            self.trip.with_user(self.driver_b).action_close()
        with self.assertRaises(AccessError):
            self.trip.with_user(self.driver_b)._h2o_update_position(1.0, 1.0)
        with self.assertRaises(AccessError):
            self.stop.with_user(self.driver_b).action_deliver()
        with self.assertRaises(AccessError):
            self.stop.with_user(self.driver_b).action_fail('not_home')
        with self.assertRaises(AccessError):
            self.stop.with_user(self.driver_b).action_skip()
        self.assertEqual(self.stop.state, 'pending')
        self.assertEqual(self.trip.state, 'on_road')

    def test_driver_writes_limited(self):
        stop = self.stop.with_user(self.driver_a)
        stop.note = 'Door code 1234'
        for vals in ({'trip_id': self.trip_b.id}, {'state': 'delivered'}, {'order_id': False}):
            with self.assertRaises(AccessError):
                stop.write(vals)
        with self.assertRaises(AccessError):
            self.trip.with_user(self.driver_a).write({'driver_id': self.driver_b.id})
        with self.assertRaises(AccessError):
            self.env['h2o.stop'].with_user(self.driver_a).create({
                'trip_id': self.trip.id, 'partner_id': self.cash_customer.id,
            })
        with self.assertRaises(AccessError):
            self.order.with_user(self.driver_a).read(['name'])

        stop.action_deliver()
        self.assertEqual(self.order.h2o_delivery_state, 'delivered')
        with self.assertRaises(AccessError):
            stop.note = 'Changed after delivery'

    def test_dispatcher_manages_all(self):
        Trip = self.env['h2o.trip'].with_user(self.dispatcher)
        self.assertEqual(Trip.search([('id', 'in', (self.trip | self.trip_b).ids)]), self.trip | self.trip_b)
        self.trip.with_user(self.dispatcher).stop_ids.action_skip()
        self.assertEqual(self.order.h2o_delivery_state, 'to_plan')
