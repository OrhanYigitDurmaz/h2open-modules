{
    'name': 'H2Open Customers',
    'version': '20.0.1.1.0',
    'category': 'H2Open',
    'summary': 'Water delivery customers, delivery zones and delivery preferences',
    'description': """
H2Open customers
================
* Customer type (home, office, reseller) and payment mode (cash, card, monthly account) on contacts,
* delivery zones (il, ilçe/mahalle names, postal codes, delivery days),
  matched automatically from the customer's address,
* delivery preferences: days, floor, elevator, notes for the driver,
* the exact location of the address, set on a map (OpenStreetMap) by
  clicking, searching the address or pasting a location or Google Maps link.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_base', 'contacts'],
    'data': [
        'security/ir.access.csv',
        'views/h2o_zone_views.xml',
        'views/res_partner_views.xml',
        'views/h2o_customer_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'h2o_customer/static/src/**/*',
        ],
    },
    'demo': [
        'demo/h2o_customer_demo.xml',
    ],
    'installable': True,
}
