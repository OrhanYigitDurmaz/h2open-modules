{
    'name': 'H2Open Telephony',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Asterisk caller ID, call log and driver app VoIP for H2Open',
    'description': """
H2Open telephony
================
Asterisk runs on the office PC and is reached over WireGuard; a VPS is the
public WebRTC (WSS) entry point for the driver app. Calls are never recorded.

* Caller ID lookup of customers for Asterisk, whatever the format of the
  Turkish phone number.
* Call log fed by Asterisk events, with a pop-up for dispatchers when a
  customer calls.
* SIP credentials for the driver app, generated at each sign-in and pushed to
  Asterisk through ARI dynamic configuration (PJSIP over WSS, WebRTC, ICE,
  A-law). They are revoked on Asterisk when they expire.
* Wakes the driver app with a high-priority push when a call comes in for a
  driver who is not registered, and cancels it when the caller hangs up.

Asterisk side: sorcery must allow dynamic ``res_pjsip`` objects through ARI,
with a ``transport-wss`` transport and an ``h2o-drivers`` dialplan context
for the driver endpoints. Asterisk sends the shared secret in the
``X-H2O-Secret`` header of its calls to ``/h2o/telephony/v1/...``.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_push', 'contacts'],
    'data': [
        'security/ir.access.csv',
        'data/ir_cron_data.xml',
        'views/h2o_call_views.xml',
        'views/h2o_sip_account_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'h2o_telephony/static/src/**/*',
        ],
    },
    'installable': True,
}
