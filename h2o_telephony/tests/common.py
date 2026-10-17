from odoo.tests import new_test_user

from odoo.addons.h2o_push.tests.common import H2oPushCommon

ARI_URL = 'http://10.66.0.2:8088'


class H2oTelephonyCommon(H2oPushCommon):
    """Mixin for test classes: Asterisk settings, a dispatcher, a driver with extension 201 and a customer."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter']
        params.set_str('h2o_telephony.ari_url', ARI_URL + '/')
        params.set_str('h2o_telephony.ari_user', 'odoo')
        params.set_str('h2o_telephony.ari_password', 'ari-pass')
        params.set_str('h2o_telephony.asterisk_secret', 'shared-secret')
        params.set_str('h2o_telephony.sip_domain', 'voip.h2open.test')
        params.set_str('h2o_telephony.wss_url', 'wss://voip.h2open.test/ws')
        params.set_int('h2o_telephony.sip_credential_hours', 8)
        cls.dispatcher = new_test_user(cls.env, login='h2o_tel_dispatcher', groups='h2o_base.group_h2o_dispatcher')
        cls.driver.name = 'Ali Driver'
        cls.driver_account = cls.env['h2o.sip.account'].create({'user_id': cls.driver.id, 'extension': '201'})
        cls.customer = cls.env['res.partner'].create({'name': 'Ayşe Yılmaz', 'phone': '+90 532 123 45 67'})
