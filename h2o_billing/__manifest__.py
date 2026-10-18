{
    'name': 'H2Open Billing',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Invoices on delivery, monthly statements and driver cash handovers',
    'description': """
H2Open billing
==============
* Cash and card customers: an invoice is posted for every delivery, and the payment collected
  at the door is registered on the cash or card journal and reconciled,
* account customers: one monthly statement invoice for all the orders delivered in the month,
  created on the 1st or from a wizard,
* cash handovers: when a trip closes, the cash the driver collected is counted and approved
  by an accountant.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_order', 'h2o_dispatch', 'account'],
    'data': [
        'security/h2o_billing_security.xml',
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/h2o_cash_handover_views.xml',
        'views/account_move_views.xml',
        'views/h2o_trip_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/h2o_statement_wizard_views.xml',
        'views/h2o_billing_menus.xml',
    ],
    'installable': True,
}
