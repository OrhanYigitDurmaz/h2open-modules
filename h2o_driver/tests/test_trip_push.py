import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged
from odoo.tests.common import MockHTTPClient

from odoo.addons.h2o_dispatch.tests.common import H2oDispatchCase
from odoo.addons.h2o_push.tests.common import FCM_URL, TOKEN_URL, H2oPushCommon


@tagged('post_install', '-at_install')
class TestTripChangedPush(H2oPushCommon, H2oDispatchCase, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.route.driver_id = cls.driver
        cls.order_1 = cls._order(cls.cash_customer, [(cls.water, 2)])
        cls.order_2 = cls._order(cls.account_customer, [(cls.water, 1)])
        cls.trip = cls.env['h2o.trip']._h2o_plan_day(cls.date, cls.route)

    def _patch_send(self):
        return patch.object(self.env.registry['h2o.push.device'], '_h2o_send', autospec=True)

    def _pushed(self, send):
        return [(call.args[1], call.args[2], call.kwargs.get('app')) for call in send.call_args_list]

    def test_no_push_while_planned(self):
        with self._patch_send() as send:
            self.trip.stop_ids[0].unlink()
            self.env['h2o.stop'].create({'trip_id': self.trip.id, 'order_id': self.order_1.id})
        send.assert_not_called()

    def test_push_on_trip_in_progress(self):
        self.trip.action_start()
        stop_1, stop_2 = self.trip.stop_ids
        with self._patch_send() as send:
            stop_2.with_user(self.dispatcher).unlink()
        self.assertEqual(self._pushed(send), [(self.driver, {
            'type': 'trip_changed', 'trip_id': self.trip.id, 'change': 'removed', 'stop_ids': str(stop_2.id),
        }, 'driver')])

        with self._patch_send() as send:
            stop = self.env['h2o.stop'].with_user(self.dispatcher).create(
                {'trip_id': self.trip.id, 'order_id': self.order_2.id})
        self.assertEqual(self._pushed(send), [(self.driver, {
            'type': 'trip_changed', 'trip_id': self.trip.id, 'change': 'added', 'stop_ids': str(stop.id),
        }, 'driver')])

        # moving a stop to another driver's trip tells both drivers
        other_trip = self.env['h2o.trip'].create({
            'date': self.date, 'vehicle_id': self.van_b.id, 'driver_id': self.driver_b.id,
        })
        other_trip.action_load()
        with self._patch_send() as send:
            stop.with_user(self.dispatcher).trip_id = other_trip
        self.assertEqual([(user, data['change'], data['trip_id']) for user, data, _app in self._pushed(send)], [
            (self.driver, 'removed', self.trip.id),
            (self.driver_b, 'added', other_trip.id),
        ])

        # other changes do not push
        with self._patch_send() as send:
            stop_1.with_user(self.driver).note = 'Ring twice'
        send.assert_not_called()

    def test_push_reaches_fcm(self):
        self.trip.action_load()
        with MockHTTPClient(url=TOKEN_URL, method='POST', return_json={'access_token': 'a', 'expires_in': 3599}), \
                MockHTTPClient(url=FCM_URL, return_json={'name': 'm/1'}) as fcm:
            self.trip.stop_ids[0].unlink()
        message = json.loads(fcm.calls[0].body)['message']
        self.assertEqual(message['token'], 'tok-driver')
        self.assertEqual(message['data']['type'], 'trip_changed')
        self.assertEqual(message['data']['change'], 'removed')
        self.assertEqual(message['data']['trip_id'], str(self.trip.id))
