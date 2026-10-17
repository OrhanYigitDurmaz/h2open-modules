{
    'name': 'H2Open Dispatch',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Delivery routes, vehicles, daily trips and delivery stops',
    'description': """
H2Open dispatch
===============
* Delivery routes grouping zones, with their days, vehicle and driver,
* daily trips: a driver and a vehicle load out, visit ordered stops and come back
  with the empties and the cash,
* delivery stops: delivered quantities, empties collected, payment, signature and photo;
  a delivery updates the order and the customer's bottle ledger,
* failed or skipped stops send the order back to planning,
* a planning wizard that fills the day's trips with the orders to deliver.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_order', 'fleet'],
    'data': [
        'security/h2o_dispatch_security.xml',
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'views/fleet_vehicle_views.xml',
        'views/h2o_route_views.xml',
        'views/h2o_zone_views.xml',
        'views/h2o_stop_views.xml',
        'views/h2o_trip_views.xml',
        'views/sale_order_views.xml',
        'wizard/h2o_trip_plan_views.xml',
        'views/h2o_dispatch_menus.xml',
    ],
    'demo': [
        'demo/h2o_dispatch_demo.xml',
    ],
    'installable': True,
}
