{
    'name': 'H2Open Subscriptions',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Recurring water deliveries that create confirmed orders ahead of the delivery day',
    'description': """
H2Open subscriptions
====================
* Recurring delivery plans per customer: products, quantities, weekly, every two weeks or monthly on a weekday,
* a daily job creates and confirms the delivery order a few days ahead (lead days in the settings),
  exactly like a phone order: delivery address, time window, empties expected, deposits and customer prices,
* never two orders for the same subscription and day,
* pause, resume and close a subscription; create the next order on demand.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_order'],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/h2o_subscription_views.xml',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        'views/h2o_subscription_menus.xml',
    ],
    'demo': [
        'demo/h2o_subscription_demo.xml',
    ],
    'installable': True,
}
