import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from odoo.tests import new_test_user

from odoo.addons.h2o_push.models import h2o_push_device

FCM_URL = 'https://fcm.googleapis.com/v1/projects/h2open-test/messages:send'
TOKEN_URL = 'https://oauth2.googleapis.com/token'


class H2oPushCommon:
    """Mixin for test classes: a configured FCM service account and a driver with a phone."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = cls.private_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        ).decode()
        cls.env['ir.config_parameter'].set_str('h2o_push.fcm_project_id', 'h2open-test')
        cls.env['ir.config_parameter'].set_str('h2o_push.fcm_service_account', json.dumps({
            'type': 'service_account',
            'project_id': 'h2open-test',
            'private_key_id': 'key1',
            'private_key': pem,
            'client_email': 'push@h2open-test.iam.gserviceaccount.com',
        }))
        cls.driver = new_test_user(cls.env, login='h2o_push_driver', password='h2o_push_driver',
                                   groups='h2o_base.group_h2o_driver')
        cls.driver_phone = cls.env['h2o.push.device'].create({
            'user_id': cls.driver.id, 'token': 'tok-driver', 'app': 'driver', 'device_name': 'Driver phone',
        })

    def setUp(self):
        super().setUp()
        h2o_push_device._access_tokens.clear()
