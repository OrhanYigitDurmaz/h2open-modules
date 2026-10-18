import json
from datetime import timedelta

from odoo import fields
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
        token = body['token']

        res = self._post('/h2o/api/v1/me', token=token)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['id'], self.driver.id)

        res = self._post('/h2o/api/v1/logout', token=token)
        self.assertEqual(res.status_code, 200, res.text)
        res = self._post('/h2o/api/v1/me', token=token)
        self.assertEqual(res.status_code, 401)

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
