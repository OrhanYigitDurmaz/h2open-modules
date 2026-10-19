{
    'name': 'H2Open Base',
    'version': '20.0.1.2.0',
    'category': 'H2Open',
    'summary': 'Menus, security groups, shared settings and app API for H2Open water delivery',
    'description': """
H2Open base
===========
Common foundation for every H2Open module:

* the H2Open top menu and its sections,
* security groups (driver, dispatcher, accountant, manager),
* weekdays used by zones, routes, customers and subscriptions,
* shared company settings (order cut-off hour),
* the bearer-token API used by the driver and customer mobile apps, with
  rotating refresh tokens, a list of signed-in devices and app crash reports.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/h2o_security.xml',
        'security/ir.access.csv',
        'data/h2o_weekday_data.xml',
        'views/h2o_menus.xml',
        'views/h2o_weekday_views.xml',
        'views/h2o_app_session_views.xml',
        'views/h2o_app_crash_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'application': True,
    'installable': True,
}
