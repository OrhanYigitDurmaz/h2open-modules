import json

from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPushApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = new_test_user(cls.env, login='h2o_push_api_driver', groups='h2o_base.group_h2o_driver')
        cls.colleague = new_test_user(cls.env, login='h2o_push_api_colleague', groups='h2o_base.group_h2o_driver')
        cls.driver_token = cls.driver._h2o_issue_app_token('test phone')
        cls.colleague_token = cls.colleague._h2o_issue_app_token('test phone')

    def _post(self, path, payload, token):
        return self.url_open(path, data=json.dumps(payload), headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % token,
        })

    def test_register_and_unregister(self):
        payload = {'token': 'fcm-1', 'platform': 'android', 'app': 'driver', 'device_name': 'Galaxy A54'}
        res = self._post('/h2o/api/v1/push/register', payload, self.driver_token)
        self.assertEqual(res.status_code, 200, res.text)
        device = self.env['h2o.push.device'].browse(res.json()['id'])
        self.assertRecordValues(device, [{'user_id': self.driver.id, 'token': 'fcm-1', 'platform': 'android',
                                          'app': 'driver', 'device_name': 'Galaxy A54', 'active': True}])

        # Registering again keeps a single device.
        res = self._post('/h2o/api/v1/push/register', payload, self.driver_token)
        self.assertEqual(res.json()['id'], device.id)

        # Another user cannot unregister someone else's token.
        res = self._post('/h2o/api/v1/push/unregister', {'token': 'fcm-1'}, self.colleague_token)
        self.assertEqual(res.status_code, 200, res.text)
        device.invalidate_recordset()
        self.assertTrue(device.active)

        res = self._post('/h2o/api/v1/push/unregister', {'token': 'fcm-1'}, self.driver_token)
        self.assertEqual(res.status_code, 200, res.text)
        device.invalidate_recordset()
        self.assertFalse(device.active)

        # The phone changes hands: the token moves to the new user and is active again.
        res = self._post('/h2o/api/v1/push/register', payload, self.colleague_token)
        self.assertEqual(res.json()['id'], device.id)
        device.invalidate_recordset()
        self.assertEqual(device.user_id, self.colleague)
        self.assertTrue(device.active)

    def test_register_bad_request(self):
        res = self._post('/h2o/api/v1/push/register', {'platform': 'android'}, self.driver_token)
        self.assertEqual(res.status_code, 400)
        res = self._post('/h2o/api/v1/push/register', {'token': 'x', 'platform': 'windows'}, self.driver_token)
        self.assertEqual(res.status_code, 400)
        res = self._post('/h2o/api/v1/push/register', {'token': 'x', 'app': 'other'}, self.driver_token)
        self.assertEqual(res.status_code, 400)

    def test_register_requires_token(self):
        res = self.url_open('/h2o/api/v1/push/register', data=json.dumps({'token': 'x'}),
                            headers={'Content-Type': 'application/json'})
        self.assertEqual(res.status_code, 401)

    def test_signed_out_device_stops_receiving_pushes(self):
        payload = {'token': 'fcm-session', 'platform': 'android', 'app': 'driver', 'device_name': 'Galaxy A54'}
        res = self._post('/h2o/api/v1/push/register', payload, self.driver_token)
        self.assertEqual(res.status_code, 200, res.text)
        device = self.env['h2o.push.device'].browse(res.json()['id'])
        other = self.env['h2o.push.device'].sudo().create({
            'user_id': self.driver.id, 'token': 'fcm-other', 'device_name': 'tablet'})
        session = device.session_id
        self.assertEqual(session.user_id, self.driver)
        self.assertEqual(session.device_name, 'test phone')

        session.action_h2o_sign_out()
        self.assertFalse(device.active)
        self.assertTrue(other.active)
