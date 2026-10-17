import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tests.common import MockHTTPClient
from odoo.tools import mute_logger

from .common import FCM_URL, TOKEN_URL, H2oPushCommon


def _b64decode(part):
    return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))


@tagged('post_install', '-at_install')
class TestPushSend(H2oPushCommon, TransactionCase):

    def _mock_token(self, **kw):
        return MockHTTPClient(url=TOKEN_URL, method='POST',
                              return_json={'access_token': 'access-1', 'expires_in': 3599}, **kw)

    def test_send_to_driver_devices(self):
        customer_phone = self.env['h2o.push.device'].create({
            'user_id': self.driver.id, 'token': 'tok-customer-app', 'app': 'customer',
        })
        with self._mock_token() as token_mock, MockHTTPClient(url=FCM_URL, return_json={'name': 'm/1'}) as fcm_mock:
            result = self.env['h2o.push.device']._h2o_send(
                self.driver, {'type': 'incoming_call', 'call_id': 42}, app='driver', ttl=30)
            self.env['h2o.push.device']._h2o_send(self.driver, {'type': 'call_cancelled'}, app='driver')

        self.assertEqual(result, {'sent': 1, 'failed': 0, 'deactivated': 0})
        # The access token is fetched once and reused for the second push.
        token_mock.assert_called_once()
        fcm_mock.assert_called(2)

        # The OAuth2 assertion is a JWT signed with the service account key.
        assertion = parse_qs(token_mock.calls[0].body)['assertion'][0]
        header, claims, signature = assertion.split('.')
        self.private_key.public_key().verify(
            _b64decode(signature), f'{header}.{claims}'.encode(), padding.PKCS1v15(), hashes.SHA256())
        self.assertEqual(json.loads(_b64decode(header)), {'alg': 'RS256', 'typ': 'JWT', 'kid': 'key1'})
        claims = json.loads(_b64decode(claims))
        self.assertEqual(claims['iss'], 'push@h2open-test.iam.gserviceaccount.com')
        self.assertEqual(claims['aud'], TOKEN_URL)
        self.assertEqual(claims['scope'], 'https://www.googleapis.com/auth/firebase.messaging')

        request = fcm_mock.calls[0]
        self.assertEqual(request.headers['Authorization'], 'Bearer access-1')
        message = json.loads(request.body)['message']
        self.assertEqual(message['token'], 'tok-driver')
        self.assertEqual(message['data'], {'type': 'incoming_call', 'call_id': '42'})
        self.assertEqual(message['android'], {'priority': 'HIGH', 'ttl': '30s'})
        self.assertNotIn('notification', message)

        logs = self.env['h2o.push.log'].search([('user_id', '=', self.driver.id)])
        self.assertEqual(len(logs), 2)
        self.assertEqual(set(logs.mapped('state')), {'sent'})
        self.assertFalse(logs.device_id & customer_phone)

    def test_notification_and_normal_priority(self):
        with self._mock_token(), MockHTTPClient(url=FCM_URL, return_json={'name': 'm/1'}) as fcm_mock:
            self.env['h2o.push.device']._h2o_send(
                self.driver, {'type': 'trip_changed'}, notification={'title': 'Trip', 'body': 'Changed'},
                priority='normal')
        message = json.loads(fcm_mock.calls[0].body)['message']
        self.assertEqual(message['notification'], {'title': 'Trip', 'body': 'Changed'})
        self.assertEqual(message['android']['priority'], 'NORMAL')
        self.assertEqual(message['apns']['headers']['apns-priority'], '5')

    @mute_logger('odoo.addons.h2o_push.models.h2o_push_device')
    def test_unregistered_token_deactivated(self):
        error = {'error': {'code': 404, 'status': 'NOT_FOUND', 'message': 'Requested entity was not found.',
                           'details': [{'@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError',
                                        'errorCode': 'UNREGISTERED'}]}}
        with self._mock_token(), MockHTTPClient(url=FCM_URL, return_status=404, return_json=error):
            result = self.env['h2o.push.device']._h2o_send(self.driver, {'type': 'x'})
        self.assertEqual(result, {'sent': 0, 'failed': 1, 'deactivated': 1})
        self.assertFalse(self.driver_phone.active)
        log = self.env['h2o.push.log'].search([('device_id', '=', self.driver_phone.id)])
        self.assertEqual(log.state, 'failed')
        self.assertIn('Requested entity was not found', log.error)

        # An archived device gets no more pushes.
        with MockHTTPClient(url=FCM_URL) as fcm_mock:
            result = self.env['h2o.push.device']._h2o_send(self.driver, {'type': 'x'})
        fcm_mock.assert_called(0)
        self.assertEqual(result['sent'], 0)

    @mute_logger('odoo.addons.h2o_push.models.h2o_push_device')
    def test_network_error_does_not_raise(self):
        def fail(request):
            raise requests.ConnectionError("network unreachable")

        with self._mock_token(side_effect=fail):
            result = self.env['h2o.push.device']._h2o_send(self.driver, {'type': 'x'})
        self.assertEqual(result, {'sent': 0, 'failed': 1, 'deactivated': 0})
        self.assertTrue(self.driver_phone.active)
        log = self.env['h2o.push.log'].search([('device_id', '=', self.driver_phone.id)])
        self.assertEqual(log.state, 'failed')
        self.assertIn('network unreachable', log.error)

        with self._mock_token(), MockHTTPClient(url=FCM_URL, side_effect=fail):
            result = self.env['h2o.push.device']._h2o_send(self.driver, {'type': 'x'})
        self.assertEqual(result['failed'], 1)
        self.assertTrue(self.driver_phone.active)

    @mute_logger('odoo.addons.h2o_push.models.h2o_push_device')
    def test_not_configured(self):
        self.env['ir.config_parameter'].set_str('h2o_push.fcm_service_account', False)
        with MockHTTPClient() as http_mock:
            result = self.env['h2o.push.device']._h2o_send(self.driver, {'type': 'x'})
        http_mock.assert_called(0)
        self.assertEqual(result['failed'], 1)

    def test_no_device_no_request(self):
        other = new_test_user(self.env, login='h2o_push_nodevice', groups='h2o_base.group_h2o_driver')
        with MockHTTPClient() as http_mock:
            result = self.env['h2o.push.device']._h2o_send(other, {'type': 'x'})
        http_mock.assert_called(0)
        self.assertEqual(result, {'sent': 0, 'failed': 0, 'deactivated': 0})

    def test_device_access(self):
        other = new_test_user(self.env, login='h2o_push_other', groups='h2o_base.group_h2o_driver')
        other_phone = self.env['h2o.push.device'].create({'user_id': other.id, 'token': 'tok-other'})
        Device = self.env['h2o.push.device'].with_user(self.driver)
        self.assertEqual(Device.search([]), self.driver_phone)
        self.assertFalse(Device.search([('id', '=', other_phone.id)]))

    def test_log_cleanup(self):
        log = self.env['h2o.push.log'].create({'user_id': self.driver.id, 'state': 'sent', 'data': {}})
        recent = self.env['h2o.push.log'].create({'user_id': self.driver.id, 'state': 'sent', 'data': {}})
        self.env.cr.execute("UPDATE h2o_push_log SET create_date = %s WHERE id = %s",
                            [fields.Datetime.now() - timedelta(days=31), log.id])
        self.env.invalidate_all()
        self.env['h2o.push.log']._gc_h2o_push_log()
        self.assertFalse(log.exists())
        self.assertTrue(recent.exists())
