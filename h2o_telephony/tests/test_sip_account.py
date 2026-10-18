import base64
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import MockHTTPClient
from odoo.tools import mute_logger

from odoo.addons.h2o_push.tests.common import FCM_URL, TOKEN_URL

from .common import ARI_URL, H2oTelephonyCommon

ARI_CONFIG_URL = ARI_URL + '/ari/asterisk/config/dynamic/res_pjsip/'


@tagged('post_install', '-at_install')
class TestSipAccount(H2oTelephonyCommon, TransactionCase):

    def _ari_fields(self, request):
        return {field['attribute']: field['value'] for field in json.loads(request.body)['fields']}

    def test_issue_credentials(self):
        now = fields.Datetime.now()
        with MockHTTPClient(url=ARI_URL, method='PUT', return_json=[]) as ari_mock, \
                patch.object(fields.Datetime, 'now', return_value=now):
            credentials = self.driver_account.with_user(self.driver)._h2o_issue_credentials()

        expires_at = now + timedelta(hours=8)
        self.assertEqual(credentials['username'], '201')
        self.assertEqual(credentials['domain'], 'voip.h2open.test')
        self.assertEqual(credentials['wss_url'], 'wss://voip.h2open.test/ws')
        self.assertEqual(credentials['ice_servers'], [])
        self.assertEqual(credentials['expires_at'], expires_at.isoformat() + 'Z')
        self.assertGreaterEqual(len(credentials['password']), 24)
        self.assertEqual(self.driver_account.password_expires_at, expires_at)

        auth, aor, endpoint = ari_mock.calls
        self.assertEqual([request.url for request in ari_mock.calls],
                         [ARI_CONFIG_URL + kind + '/201' for kind in ('auth', 'aor', 'endpoint')])
        self.assertEqual(auth.headers['Authorization'], 'Basic ' + base64.b64encode(b'odoo:ari-pass').decode())
        self.assertEqual(self._ari_fields(auth), {
            'auth_type': 'userpass', 'username': '201', 'password': credentials['password'],
        })
        self.assertEqual(self._ari_fields(aor)['max_contacts'], '1')
        endpoint_fields = self._ari_fields(endpoint)
        self.assertEqual({key: endpoint_fields[key] for key in ('transport', 'aors', 'auth', 'webrtc', 'ice_support',
                                                                 'disallow', 'allow')}, {
            'transport': 'transport-wss', 'aors': '201', 'auth': '201', 'webrtc': 'yes', 'ice_support': 'yes',
            'disallow': 'all', 'allow': 'alaw',
        })
        self.assertEqual(endpoint_fields['callerid'], '"Ali Driver" <201>')

        # Each sign-in gets a different password, which is never stored.
        with MockHTTPClient(url=ARI_URL, method='PUT', return_json=[]):
            second = self.driver_account._h2o_issue_credentials()
        self.assertNotEqual(second['password'], credentials['password'])
        self.env.flush_all()
        self.env.cr.execute("SELECT row_to_json(a)::text FROM h2o_sip_account a WHERE id = %s",
                            [self.driver_account.id])
        self.assertNotIn(second['password'], self.env.cr.fetchone()[0])

    def test_asterisk_errors(self):
        with MockHTTPClient(url=ARI_URL, return_status=500, return_body='boom'), \
                self.assertRaisesRegex(UserError, 'boom'):
            self.driver_account._h2o_issue_credentials()
        self.assertFalse(self.driver_account.password_expires_at)

        self.env['ir.config_parameter'].set_str('h2o_telephony.ari_url', False)
        with self.assertRaises(UserError):
            self.driver_account._h2o_issue_credentials()

    @mute_logger('odoo.addons.h2o_telephony.models.h2o_sip_account')
    def test_cron_revokes_expired_credentials(self):
        other = self.env['h2o.sip.account'].create({'user_id': self.dispatcher.id, 'extension': '100'})
        self.driver_account.password_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        other.password_expires_at = fields.Datetime.now() + timedelta(hours=1)
        with MockHTTPClient(url=ARI_URL, method='DELETE', return_status=204) as ari_mock:
            self.env['h2o.sip.account']._cron_h2o_revoke_expired()
        self.assertEqual([request.url for request in ari_mock.calls], [ARI_CONFIG_URL + 'auth/201'])
        self.assertFalse(self.driver_account.password_expires_at)
        self.assertTrue(other.password_expires_at)

        # Asterisk down: kept for the next run.
        other.password_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        with MockHTTPClient(url=ARI_URL, return_status=503):
            self.env['h2o.sip.account']._cron_h2o_revoke_expired()
        self.assertTrue(other.password_expires_at)

        # Already gone on Asterisk.
        with MockHTTPClient(url=ARI_URL, return_status=404):
            self.env['h2o.sip.account']._cron_h2o_revoke_expired()
        self.assertFalse(other.password_expires_at)

    def test_extension_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['h2o.sip.account'].create({'user_id': self.dispatcher.id, 'extension': '1a'})

    def test_driver_reads_only_own_account(self):
        other = self.env['h2o.sip.account'].create({'user_id': self.dispatcher.id, 'extension': '100'})
        Account = self.env['h2o.sip.account'].with_user(self.driver)
        self.assertEqual(Account.search([]), self.driver_account)
        self.assertFalse(Account.search([('id', '=', other.id)]))
        self.assertFalse(Account.has_access('write'))

    def test_wake_and_cancel_push(self):
        token = MockHTTPClient(url=TOKEN_URL, return_json={'access_token': 'a', 'expires_in': 3600})
        with token, MockHTTPClient(url=FCM_URL, return_json={'name': 'm/1'}) as fcm_mock:
            result = self.driver_account._h2o_wake('1700000000.9', '05321234567')
            self.driver_account._h2o_cancel('1700000000.9')
        self.assertEqual(result['sent'], 1)
        wake, cancel = (json.loads(request.body)['message'] for request in fcm_mock.calls)
        self.assertEqual(wake['token'], 'tok-driver')
        self.assertEqual(wake['android']['priority'], 'HIGH')
        self.assertEqual(wake['data'], {
            'type': 'incoming_call', 'call_id': '1700000000.9', 'extension': '201', 'caller': '05321234567',
            'caller_name': 'Ayşe Yılmaz', 'partner_id': str(self.customer.id),
        })
        self.assertEqual(cancel['data'], {'type': 'call_cancelled', 'call_id': '1700000000.9', 'extension': '201'})
