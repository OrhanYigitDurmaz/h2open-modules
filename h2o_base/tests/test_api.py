import json
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestAppApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = new_test_user(cls.env, login='h2o_api_driver', password='h2o_api_driver',
                                   groups='h2o_base.group_h2o_driver')
        cls.plain = new_test_user(cls.env, login='h2o_api_plain', password='h2o_api_plain',
                                  groups='base.group_user')

    def _post(self, path, payload=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer %s' % token
        return self.url_open(path, data=json.dumps(payload or {}), headers=headers)

    def test_login_me_logout(self):
        res = self._post('/h2o/api/v1/login', {'login': 'h2o_api_driver', 'password': 'h2o_api_driver',
                                               'device_name': 'test phone'})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIn('driver', body['user']['roles'])
        token = body['access_token']
        self.assertTrue(body['refresh_token'])
        self.assertEqual(body['token'], token)
        self.assertTrue(body['access_expires_at'].endswith('Z'))
        self.assertAlmostEqual(body['access_expires_in'], 24 * 3600, delta=60)
        self.assertAlmostEqual(body['refresh_expires_in'], 90 * 86400, delta=60)

        res = self._post('/h2o/api/v1/me', token=token)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['id'], self.driver.id)

        res = self._post('/h2o/api/v1/logout', token=token)
        self.assertEqual(res.status_code, 200, res.text)
        res = self._post('/h2o/api/v1/me', token=token)
        self.assertEqual(res.status_code, 401)
        session = self.env['h2o.app.session'].search([('user_id', '=', self.driver.id)])
        self.assertEqual(session.state, 'revoked')
        self.assertEqual(session.revoke_reason, 'logout')
        self.assertEqual(session.device_name, 'test phone')
        res = self._refresh(body['refresh_token'])
        self.assertEqual(res.status_code, 401)

    def _login(self, device_name='phone'):
        res = self._post('/h2o/api/v1/login', {'login': 'h2o_api_driver', 'password': 'h2o_api_driver',
                                               'device_name': device_name})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _refresh(self, refresh_token):
        return self._post('/h2o/api/v1/token/refresh', {'refresh_token': refresh_token})

    def _session(self, tokens):
        ref = tokens['refresh_token'].split('.', 1)[0]
        return self.env['h2o.app.session'].sudo().search([('ref', '=', ref)])

    def test_refresh_rotates_both_tokens(self):
        first = self._login()
        res = self._refresh(first['refresh_token'])
        self.assertEqual(res.status_code, 200, res.text)
        second = res.json()
        self.assertNotEqual(second['access_token'], first['access_token'])
        self.assertNotEqual(second['refresh_token'], first['refresh_token'])
        self.assertNotIn('user', second)
        # The old access token is gone, the new one works.
        self.assertEqual(self._post('/h2o/api/v1/me', token=first['access_token']).status_code, 401)
        self.assertEqual(self._post('/h2o/api/v1/me', token=second['access_token']).status_code, 200)
        # Same device, rotated in place; only hashes are stored.
        session = self._session(second)
        self.assertEqual(session, self._session(first))
        self.assertEqual(session.state, 'active')
        self.assertNotIn(second['refresh_token'], (session.refresh_hash, session.previous_hash))

    def test_reused_refresh_token_signs_device_out(self):
        first = self._login()
        other_device = self._login('other phone')
        second = self._refresh(first['refresh_token']).json()
        self._session(first).rotated_at = fields.Datetime.now() - timedelta(minutes=5)

        res = self._refresh(first['refresh_token'])
        self.assertEqual(res.status_code, 401)
        session = self._session(first)
        self.assertEqual(session.state, 'revoked')
        self.assertEqual(session.revoke_reason, 'reuse')
        # The thief and the phone are both out, and must sign in again.
        self.assertEqual(self._refresh(second['refresh_token']).status_code, 401)
        self.assertEqual(self._post('/h2o/api/v1/me', token=second['access_token']).status_code, 401)
        # Other devices of the same user are not touched.
        self.assertEqual(self._post('/h2o/api/v1/me', token=other_device['access_token']).status_code, 200)
        self.assertEqual(self._refresh(other_device['refresh_token']).status_code, 200)

    def test_refresh_retry_right_after_rotation(self):
        """A phone that lost the refresh answer retries with the same token."""
        first = self._login()
        lost = self._refresh(first['refresh_token']).json()
        res = self._refresh(first['refresh_token'])
        self.assertEqual(res.status_code, 200, res.text)
        retried = res.json()
        self.assertEqual(self._post('/h2o/api/v1/me', token=lost['access_token']).status_code, 401)
        self.assertEqual(self._post('/h2o/api/v1/me', token=retried['access_token']).status_code, 200)
        # Only one retry: a third use of the first token is reuse.
        self.assertEqual(self._refresh(first['refresh_token']).status_code, 401)
        self.assertEqual(self._session(first).revoke_reason, 'reuse')

    def test_refresh_bad_or_expired(self):
        for bad in (None, '', 'nodot', 'unknown.secret', 42):
            self.assertEqual(self._refresh(bad).status_code, 401, bad)
        tokens = self._login()
        # A wrong secret with a known reference counts as reuse.
        ref = tokens['refresh_token'].split('.', 1)[0]
        self._session(tokens).rotated_at = fields.Datetime.now() - timedelta(minutes=5)
        self.assertEqual(self._refresh(ref + '.forged').status_code, 401)
        self.assertEqual(self._session(tokens).state, 'revoked')

        tokens = self._login()
        self._session(tokens).refresh_expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertEqual(self._refresh(tokens['refresh_token']).status_code, 401)

    def test_settings_drive_lifetimes(self):
        self.driver.company_id.write({'h2o_app_access_hours': 2, 'h2o_app_refresh_days': 7})
        tokens = self._login()
        self.assertAlmostEqual(tokens['access_expires_in'], 2 * 3600, delta=60)
        self.assertAlmostEqual(tokens['refresh_expires_in'], 7 * 86400, delta=60)
        session = self._session(tokens)
        self.assertAlmostEqual(session.refresh_expires_at, fields.Datetime.now() + timedelta(days=7),
                               delta=timedelta(minutes=1))

    def test_manager_signs_device_out(self):
        tokens = self._login()
        manager = new_test_user(self.env, login='h2o_api_manager', groups='h2o_base.group_h2o_manager')
        session = self.env['h2o.app.session'].with_user(manager).search([('user_id', '=', self.driver.id)])
        self.assertEqual(len(session), 1)
        session.action_h2o_sign_out()
        self.assertEqual(session.state, 'revoked')
        self.assertEqual(session.revoke_reason, 'manager')
        self.assertEqual(self._post('/h2o/api/v1/me', token=tokens['access_token']).status_code, 401)
        self.assertEqual(self._refresh(tokens['refresh_token']).status_code, 401)

    def test_other_users_cannot_see_or_sign_out(self):
        self._login()
        with self.assertRaises(AccessError):
            self.env['h2o.app.session'].with_user(self.driver).search([])
        session = self.env['h2o.app.session'].search([('user_id', '=', self.driver.id)])
        with self.assertRaises(AccessError):
            session.with_user(self.driver).action_h2o_sign_out()

    def test_archive_or_password_change_signs_out(self):
        tokens = self._login()
        self.driver.password = 'h2o_api_driver_new'
        self.assertEqual(self._session(tokens).revoke_reason, 'user')
        self.assertEqual(self._refresh(tokens['refresh_token']).status_code, 401)

        self.driver.password = 'h2o_api_driver'
        tokens = self._login()
        self.driver.active = False
        self.assertEqual(self._session(tokens).state, 'revoked')
        self.driver.active = True
        self.assertEqual(self._refresh(tokens['refresh_token']).status_code, 401)

    def test_last_used_moves(self):
        tokens = self._login()
        session = self._session(tokens)
        old = fields.Datetime.now() - timedelta(hours=1)
        session.last_used = old
        self.assertEqual(self._post('/h2o/api/v1/me', token=tokens['access_token']).status_code, 200)
        session.invalidate_recordset()
        self.assertGreater(session.last_used, old)

    def test_wrong_password(self):
        res = self._post('/h2o/api/v1/login', {'login': 'h2o_api_driver', 'password': 'nope'})
        self.assertEqual(res.status_code, 401)

    def test_user_without_role_refused(self):
        res = self._post('/h2o/api/v1/login', {'login': 'h2o_api_plain', 'password': 'h2o_api_plain'})
        self.assertEqual(res.status_code, 401)

    def test_token_of_other_scope_rejected(self):
        expiration = fields.Datetime.now() + timedelta(days=1)
        rpc_key = self.env['res.users.apikeys'].with_user(self.driver).sudo()._generate('rpc', 'x', expiration)
        res = self._post('/h2o/api/v1/me', token=rpc_key)
        self.assertEqual(res.status_code, 401)
        res = self._post('/h2o/api/v1/me', token='not-a-token')
        self.assertEqual(res.status_code, 401)

    def test_crash_reports(self):
        token = self._login()['access_token']
        res = self._post('/h2o/api/v1/crashes', {'reports': [
            {'stack_trace': 'java.lang.IllegalStateException: boom\n\tat tr.h2open.driver.X.y(X.kt:1)',
             'app': 'driver', 'app_version': '1.2.0', 'device': 'Samsung SM-A155F', 'os_version': '15',
             'occurred_at': '2026-10-19T08:30:00Z'},
            {'stack_trace': '   '},
        ]}, token=token)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {'received': 1})
        crash = self.env['h2o.app.crash'].search([('user_id', '=', self.driver.id)])
        self.assertEqual(crash.exception, 'java.lang.IllegalStateException: boom')
        self.assertEqual(crash.app_version, '1.2.0')
        self.assertEqual(fields.Datetime.to_string(crash.occurred_at), '2026-10-19 08:30:00')

        res = self._post('/h2o/api/v1/crashes', {'reports': 'nope'}, token=token)
        self.assertEqual(res.status_code, 400)
        res = self._post('/h2o/api/v1/crashes', {'reports': []})
        self.assertEqual(res.status_code, 401)
