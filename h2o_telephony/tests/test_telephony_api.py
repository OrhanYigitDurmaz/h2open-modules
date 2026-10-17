import json

from odoo.tests import HttpCase, tagged
from odoo.tests.common import MockHTTPClient

from odoo.addons.h2o_push.tests.common import FCM_URL, TOKEN_URL

from .common import ARI_URL, H2oTelephonyCommon


@tagged('post_install', '-at_install')
class TestTelephonyApi(H2oTelephonyCommon, HttpCase):

    def _asterisk(self, path, payload, secret='shared-secret'):
        headers = {'Content-Type': 'application/json'}
        if secret is not None:
            headers['X-H2O-Secret'] = secret
        return self.url_open('/h2o/telephony/v1/' + path, data=json.dumps(payload), headers=headers)

    def test_secret_required(self):
        self.assertEqual(self._asterisk('lookup', {'number': '05321234567'}, secret=None).status_code, 403)
        self.assertEqual(self._asterisk('lookup', {'number': '05321234567'}, secret='wrong').status_code, 403)
        self.env['ir.config_parameter'].set_str('h2o_telephony.asterisk_secret', False)
        self.assertEqual(self._asterisk('lookup', {'number': '05321234567'}, secret='').status_code, 403)

    def test_lookup(self):
        res = self._asterisk('lookup', {'number': '+905321234567'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {'name': 'Ayşe Yılmaz', 'partner_id': self.customer.id})
        res = self._asterisk('lookup', {'number': '05550000000'})
        self.assertEqual(res.json(), {'name': '', 'partner_id': None})

    def test_events(self):
        res = self._asterisk('event', {'uniqueid': '1700000000.5', 'event': 'ring', 'caller': '05321234567',
                                       'called': '02742234567'})
        self.assertEqual(res.status_code, 200, res.text)
        call = self.env['h2o.call'].browse(res.json()['call_id'])
        self.assertEqual(res.json()['partner_id'], self.customer.id)
        self.assertEqual(call.state, 'ringing')

        res = self._asterisk('event', {'uniqueid': '1700000000.5', 'event': 'answer', 'extension': 201})
        self.assertEqual(res.json()['state'], 'answered')
        res = self._asterisk('event', {'uniqueid': '1700000000.5', 'event': 'hangup'})
        self.assertEqual(res.json()['state'], 'ended')
        call.invalidate_recordset()
        self.assertEqual(call.user_id, self.driver)

        self.assertEqual(self._asterisk('event', {'uniqueid': '1', 'event': 'transfer'}).status_code, 400)
        self.assertEqual(self._asterisk('event', {'event': 'ring'}).status_code, 400)
        self.assertEqual(self._asterisk('event', {'uniqueid': '1', 'event': 'ring', 'direction': 'x'}).status_code,
                         400)

    def test_wake_and_cancel(self):
        token = MockHTTPClient(url=TOKEN_URL, return_json={'access_token': 'a', 'expires_in': 3600})
        with token, MockHTTPClient(url=FCM_URL, return_json={'name': 'm/1'}) as fcm_mock:
            res = self._asterisk('wake', {'extension': '201', 'call_id': 'c-1', 'caller': '05321234567'})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json()['sent'], 1)
            res = self._asterisk('cancel', {'extension': '201', 'call_id': 'c-1'})
            self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual([json.loads(request.body)['message']['data']['type'] for request in fcm_mock.calls],
                         ['incoming_call', 'call_cancelled'])

        self.assertEqual(self._asterisk('wake', {'extension': '999', 'call_id': 'c-2'}).status_code, 404)
        self.assertEqual(self._asterisk('cancel', {'call_id': 'c-2'}).status_code, 400)

    def test_sip_credentials(self):
        app_token = self.driver._h2o_issue_app_token('test phone')
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer %s' % app_token}
        with MockHTTPClient(url=ARI_URL, method='PUT', return_json=[]) as ari_mock:
            res = self.url_open('/h2o/api/v1/sip/credentials', data='{}', headers=headers)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body['username'], '201')
        self.assertEqual(body['wss_url'], 'wss://voip.h2open.test/ws')
        self.assertEqual(body['ice_servers'], [])
        self.assertTrue(body['password'])
        ari_mock.assert_called(3)

        # A user without SIP account gets a 404.
        dispatcher_token = self.dispatcher._h2o_issue_app_token('test phone')
        res = self.url_open('/h2o/api/v1/sip/credentials', data='{}', headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer %s' % dispatcher_token})
        self.assertEqual(res.status_code, 404)
