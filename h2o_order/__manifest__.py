{
    'name': 'H2Open Orders',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Water delivery orders, phone orders, delivery dates, deposits and prices per customer type',
    'description': """
H2Open orders
=============
* Delivery information on sales orders: channel, delivery date and time window, zone, empties expected,
* the next delivery date of a customer from its delivery days and the company cut-off hour,
* bottle deposit lines added automatically for the bottles a customer ends up holding,
* one pricelist per customer type (home, office, reseller),
* a quick phone order form for dispatchers.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_customer', 'h2o_container', 'sale'],
    'data': [
        'security/h2o_order_security.xml',
        'security/ir.access.csv',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/h2o_quick_order_views.xml',
        'views/h2o_order_menus.xml',
    ],
    'demo': [
        'demo/h2o_order_demo.xml',
    ],
    'installable': True,
}
