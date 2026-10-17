import json

from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.h2o_dispatch.tests.common import H2oDispatchCase

PREFIX = '/h2o/api/v1/driver'


@tagged('post_install', '-at_install')
class TestDriverApi(HttpCase, H2oDispatchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order_1 = cls._order(cls.cash_customer, [(cls.water, 3)], empties=1)
        cls.order_2 = cls._order(cls.account_customer, [(cls.water, 2)], empties=2)
        cls.order_3 = cls._order(cls.account_customer, [(cls.water_5l, 4)])
        cls.trip = cls.env['h2o.trip']._h2o_plan_day(cls.date, cls.route)
        cls.stop_1, cls.stop_2, cls.stop_3 = cls.trip.stop_ids
        cls.token_a = cls.driver_a._h2o_issue_app_token('phone A')
        cls.token_b = cls.driver_b._h2o_issue_app_token('phone B')

    def _call(self, path, payload=None, token=None, method='POST'):
        headers = {'Authorization': 'Bearer %s' % (token or self.token_a)}
        if method == 'GET':
            return self.url_open(PREFIX + path, headers=headers)
        headers['Content-Type'] = 'application/json'
        return self.url_open(PREFIX + path, data=json.dumps(payload or {}), headers=headers)

    def _ok(self, *args, **kwargs):
        res = self._call(*args, **kwargs)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_trips_and_detail(self):
        trips = self._ok('/trips?date=2030-01-07', method='GET')
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0]['id'], self.trip.id)
        self.assertEqual(trips[0]['date'], '2030-01-07')
        self.assertEqual(trips[0]['stop_count'], 3)
        self.assertEqual(trips[0]['vehicle']['license_plate'], '06 TST 01')
        self.assertEqual(self._ok('/trips', method='GET'), [], "no trip today")
        self.assertEqual(self._call('/trips?date=07/01/2030', method='GET').status_code, 400)

        trip = self._ok(f'/trips/{self.trip.id}', method='GET')
        self.assertEqual([stop['id'] for stop in trip['stops']], self.trip.stop_ids.ids)
        stop = trip['stops'][0]
        self.assertEqual(stop['order']['name'], self.order_1.name)
        self.assertEqual(stop['order']['empties_expected'], 1)
        self.assertEqual(stop['partner']['name'], 'Cash Customer')
        self.assertEqual(stop['partner']['latitude'], 39.92)
        self.assertEqual(stop['payment_mode'], 'cash')
        self.assertAlmostEqual(stop['amount_due'], self.order_1.amount_total)
        water_line = next(line for line in stop['lines'] if line['product_id'] == self.water.id)
        self.assertEqual(water_line['qty_planned'], 3)
        self.assertEqual(water_line['product_kind'], 'water_returnable')
        self.assertIsNone(trip['stops'][1]['partner']['latitude'])

    def test_delivery_round(self):
        self.assertEqual(self._ok(f'/trips/{self.trip.id}/start')['state'], 'on_road')
        self.assertEqual(self._ok('/position', {'trip_id': self.trip.id, 'latitude': 39.9, 'longitude': 32.8}),
                         {'ok': True})
        self.assertAlmostEqual(self.trip.last_latitude, 39.9)
        self.assertEqual(self._call('/position', {'trip_id': self.trip.id, 'latitude': 'x'}).status_code, 400)

        # the driver goes to the third stop first
        trip = self._ok('/stops/reorder', {'trip_id': self.trip.id, 'stop_ids': [self.stop_3.id, self.stop_1.id]})
        self.assertEqual([stop['id'] for stop in trip['stops']], [self.stop_3.id, self.stop_2.id, self.stop_1.id])
        self.assertEqual(
            self._call('/stops/reorder', {'trip_id': self.trip.id, 'stop_ids': [self.stop_1.id, 999999]}).status_code,
            400)

        res = self._call(f'/stops/{self.stop_1.id}/deliver', {'signature': 'not base64!'})
        self.assertEqual(res.status_code, 400)
        stop = self._ok(f'/stops/{self.stop_1.id}/deliver', {
            'lines': [{'product_id': self.water.id, 'qty_delivered': 2}],
            'empties_collected': 1,
            'payment_method': 'cash',
            'payment_amount': 240.0,
            'signature': 'aGVsbG8=',
            'latitude': 39.92,
            'longitude': 32.85,
        })
        self.assertEqual(stop['state'], 'delivered')
        self.assertEqual(stop['payment_amount'], 240.0)
        self.assertEqual(self.order_1.h2o_delivery_state, 'delivered')
        self.assertEqual(self.order_1.order_line.filtered(lambda l: l.product_id == self.water).qty_delivered, 2)
        self.assertEqual(self.cash_customer.h2o_bottle_balance, 1)
        self.assertTrue(self.stop_1.signature)
        # delivering twice is a state error
        with mute_logger('odoo.http'):
            self.assertEqual(self._call(f'/stops/{self.stop_1.id}/deliver').status_code, 422)

        self.assertEqual(self._call(f'/stops/{self.stop_2.id}/fail', {'reason': 'lost'}).status_code, 400)
        stop = self._ok(f'/stops/{self.stop_2.id}/fail', {'reason': 'not_home', 'note': 'Closed'})
        self.assertEqual((stop['state'], stop['failure_reason']), ('failed', 'not_home'))
        self.assertEqual(self.order_2.h2o_delivery_state, 'to_plan')

        with mute_logger('odoo.http'):
            self.assertEqual(self._call(f'/trips/{self.trip.id}/close').status_code, 422)
        self.assertEqual(self._ok(f'/stops/{self.stop_3.id}/skip')['state'], 'skipped')
        trip = self._ok(f'/trips/{self.trip.id}/close')
        self.assertEqual(trip['state'], 'closed')
        self.assertEqual(trip['cash_expected'], 240.0)

    def test_other_driver_gets_nothing(self):
        self.trip.action_start()
        self.assertEqual(self._ok('/trips?date=2030-01-07', token=self.token_b, method='GET'), [])
        self.assertEqual(self._call(f'/trips/{self.trip.id}', token=self.token_b, method='GET').status_code, 404)
        for path, payload in (
            (f'/trips/{self.trip.id}/close', {}),
            (f'/stops/{self.stop_1.id}/deliver', {}),
            (f'/stops/{self.stop_1.id}/fail', {'reason': 'not_home'}),
            (f'/stops/{self.stop_1.id}/skip', {}),
            ('/stops/reorder', {'trip_id': self.trip.id, 'stop_ids': [self.stop_1.id]}),
            ('/position', {'trip_id': self.trip.id, 'latitude': 1.0, 'longitude': 1.0}),
        ):
            self.assertEqual(self._call(path, payload, token=self.token_b).status_code, 404, path)
        self.assertEqual(self.trip.stop_ids.mapped('state'), ['pending'] * 3)
        self.assertFalse(self.trip.last_position_at)

    def test_driver_role_required(self):
        accountant = new_test_user(self.env, login='h2o_driver_api_accountant', groups='h2o_base.group_h2o_accountant')
        token = accountant._h2o_issue_app_token('office')
        self.assertEqual(self._call('/trips', token=token, method='GET').status_code, 403)
        res = self.url_open(PREFIX + '/trips')
        self.assertEqual(res.status_code, 401)
