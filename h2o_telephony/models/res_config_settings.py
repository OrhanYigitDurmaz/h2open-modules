from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    h2o_telephony_ari_url = fields.Char(
        string="ARI URL",
        config_parameter='h2o_telephony.ari_url',
        help="Asterisk REST Interface over WireGuard, e.g. http://10.66.0.2:8088",
    )
    h2o_telephony_ari_user = fields.Char(string="ARI User", config_parameter='h2o_telephony.ari_user')
    h2o_telephony_ari_password = fields.Char(
        string="ARI Password",
        config_parameter='h2o_telephony.ari_password',
        groups='base.group_system',
    )
    h2o_telephony_asterisk_secret = fields.Char(
        string="Asterisk Shared Secret",
        config_parameter='h2o_telephony.asterisk_secret',
        groups='base.group_system',
        help="Sent by Asterisk in the X-H2O-Secret header. Asterisk calls are refused while it is empty.",
    )
    h2o_telephony_sip_domain = fields.Char(string="SIP Domain", config_parameter='h2o_telephony.sip_domain')
    h2o_telephony_wss_url = fields.Char(
        string="WebSocket URL",
        config_parameter='h2o_telephony.wss_url',
        help="Public WSS address the driver app registers to, e.g. wss://voip.example.com/ws",
    )
    h2o_telephony_sip_credential_hours = fields.Integer(
        string="SIP Credential Lifetime (hours)",
        config_parameter='h2o_telephony.sip_credential_hours',
        default=12,
    )
