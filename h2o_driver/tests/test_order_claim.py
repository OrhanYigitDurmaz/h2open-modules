import json
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.h2o_dispatch.tests.common import H2oDispatchCase

PREFIX = '/h2o/api/v1/driver'


@tagged('post_install', '-at_install')
class TestOrderClaim(HttpCase, H2oDispatchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = cls.driver_a._h2o_today()
        cls.outside = cls.env['res.partner'].create({'name': 'Far Customer', 'zip': '99999', 'city': 'Elsewhere'})
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

    def _patch_send(self):
        return patch.object(self.env.registry['h2o.push.device'], '_h2o_send', autospec=True)

    def _pushed(self, send):
        return [(call.args[1], call.args[2]) for call in send.call_args_list]

    def test_push_on_confirm(self):
        with self._patch_send() as send:
            order = self._order(self.cash_customer, [(self.water, 2)], delivery_date=self.today)
        # the order's zone is on driver A's route: only driver A hears of it
        ((users, data),) = self._pushed(send)
        self.assertEqual(users, self.driver_a)
        self.assertEqual(data['type'], 'order_open')
        self.assertEqual(data['order_id'], order.id)
        self.assertEqual(data['customer'], 'Cash Customer')
        self.assertEqual(data['delivery_date'], fields.Date.to_string(self.today))
        self.assertEqual(send.call_args.kwargs['app'], 'driver')

        with self._patch_send() as send:
            self._order(self.outside, [(self.water, 1)])
        ((users, data),) = self._pushed(send)
        self.assertIn(self.driver_a, users)
        self.assertIn(self.driver_b, users)

        # subscription orders and quotations do not push
        with self._patch_send() as send:
            order = self._order(self.cash_customer, [(self.water, 1)], confirm=False)
            order.h2o_channel = 'subscription'
            order.action_confirm()
            self._order(self.cash_customer, [(self.water, 1)], confirm=False)
        send.assert_not_called()

    def test_list_claim_and_release(self):
        order_1 = self._order(self.cash_customer, [(self.water, 3)], empties=1, delivery_date=self.today)
        order_2 = self._order(self.outside, [(self.water_5l, 2)], delivery_date=self.today)
        mine = (order_1 | order_2).ids
        orders = [o for o in self._ok('/orders', method='GET') if o['id'] in mine]
        self.assertEqual([o['id'] for o in orders], [order_1.id, order_2.id], "own zone first")
        self.assertTrue(orders[0]['my_zone'])
        self.assertFalse(orders[1]['my_zone'])
        self.assertEqual(orders[0]['partner']['name'], 'Cash Customer')
        self.assertEqual(orders[0]['empties_expected'], 1)
        self.assertAlmostEqual(orders[0]['amount_total'], order_1.amount_total)
        water = next(line for line in orders[0]['lines'] if line['product_id'] == self.water.id)
        self.assertEqual(water['qty'], 3)
        self.assertEqual([o['id'] for o in self._ok('/orders', token=self.token_b, method='GET') if o['id'] in mine],
                         [order_1.id, order_2.id])

        with self._patch_send() as send:
            res = self._ok(f'/orders/{order_2.id}/claim', token=self.token_b)
        self.assertEqual(res['stop']['order']['id'], order_2.id)
        self.assertTrue(res['stop']['claimed'])
        self.assertEqual(res['trip']['stop_count'], 1)
        # the other drivers drop it from their list
        ((users, data),) = self._pushed(send)
        self.assertEqual(data, {'type': 'order_claimed', 'order_id': order_2.id})
        self.assertIn(self.driver_a, users)
        self.assertNotIn(self.driver_b, users)
        self.assertEqual([o['id'] for o in self._ok('/orders', method='GET') if o['id'] in mine], [order_1.id])
        trip = self._ok(f'/trips/{res["trip"]["id"]}', token=self.token_b, method='GET')
        self.assertEqual(trip['stops'][0]['id'], res['stop']['id'])

        self.assertEqual(self._call(f'/orders/{order_2.id}/claim').status_code, 409)
        self.assertEqual(self._call('/orders/999999/claim').status_code, 404)

        # driver A cannot give back driver B's order; driver B can
        self.assertEqual(self._call(f'/stops/{res["stop"]["id"]}/release').status_code, 404)
        with self._patch_send() as send:
            trip = self._ok(f'/stops/{res["stop"]["id"]}/release', token=self.token_b)
        self.assertEqual(trip['stop_count'], 0)
        self.assertEqual(order_2.h2o_delivery_state, 'to_plan')
        ((users, data),) = self._pushed(send)
        self.assertEqual(data['type'], 'order_open')
        self.assertIn(self.driver_a, users)
        self.assertNotIn(self.driver_b, users)

    def test_planned_stops_cannot_be_released(self):
        order = self._order(self.cash_customer, [(self.water, 1)])
        stop = self.env['h2o.trip']._h2o_plan_day(self.date, self.route).stop_ids
        self.assertEqual(stop.order_id, order)
        with mute_logger('odoo.http'):
            self.assertEqual(self._call(f'/stops/{stop.id}/release').status_code, 422)
