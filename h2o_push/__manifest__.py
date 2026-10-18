{
    'name': 'H2Open Push Notifications',
    'version': '20.0.1.1.0',
    'category': 'H2Open',
    'summary': 'Firebase Cloud Messaging push notifications to the H2Open mobile apps',
    'description': """
H2Open push notifications
=========================
* Registers the FCM tokens of the driver and customer apps.
* Sends data and notification messages through the FCM HTTP v1 API,
  authenticated with a Google service account (OAuth2, JWT RS256).
* Keeps a 30-day log of every push sent.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_base'],
    'data': [
        'security/ir.access.csv',
        'views/h2o_push_device_views.xml',
        'views/h2o_push_log_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
}
