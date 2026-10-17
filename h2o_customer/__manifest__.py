{
    'name': 'H2Open Customers',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Water delivery customers, delivery zones and delivery preferences',
    'description': """
H2Open customers
================
* Customer type (home, office, reseller) and payment mode (cash, card, monthly account) on contacts,
* delivery zones (il, ilçe/mahalle names, postal codes, delivery days),
  matched automatically from the customer's address,
* delivery preferences: days, floor, elevator, notes for the driver.
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
    'demo': [
        'demo/h2o_customer_demo.xml',
    ],
    'installable': True,
}
