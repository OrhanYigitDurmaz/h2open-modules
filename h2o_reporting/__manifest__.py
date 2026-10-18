{
    'name': 'H2Open Reporting',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Deliveries, bottles outstanding, cash collected and route performance',
    'description': """
H2Open reporting
================
Pivot and graph reports for the water delivery business:

* deliveries per day, zone, route and driver,
* bottles outstanding per customer and zone,
* cash collected at the door and handed in by drivers,
* route performance: stops per trip and delivery success rate.

Installing this module installs every H2Open module.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': [
        'h2o_billing',
        'h2o_driver',
        'h2o_stock',
        'h2o_subscription',
        'h2o_telephony',
    ],
    'data': [
        'security/ir.access.csv',
        'views/h2o_report_delivery_views.xml',
        'views/h2o_reporting_views.xml',
        'views/h2o_reporting_menus.xml',
    ],
    'installable': True,
}
