{
    'name': 'H2Open Bottles and Deposits',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Water products, returnable bottle ledger per customer and bottle deposits',
    'description': """
H2Open bottles and deposits
===========================
* Water products: returnable 19 L bottles, packaged water, empty bottles and deposit products,
* the bottle ledger: every bottle given to or taken back from a customer, with the deposit charged or refunded,
* bottle and deposit balances per customer, always computed from the ledger,
* deposits booked on a liability account.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_customer', 'product', 'account'],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/h2o_product_data.xml',
        'views/product_views.xml',
        'views/h2o_container_move_views.xml',
        'report/h2o_container_balance_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/h2o_container_menus.xml',
    ],
    'demo': [
        'demo/h2o_container_demo.xml',
    ],
    'installable': True,
}
