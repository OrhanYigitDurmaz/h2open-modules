{
    'name': 'H2Open Stock',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'Warehouse and vehicle stock of full and empty bottles, moved once per trip',
    'description': """
H2Open stock
============
* Water and empty bottle products are storable: the warehouse knows its full and empty bottles,
* one stock location per delivery vehicle, under its depot warehouse,
* trip load lines: products planned from the stops, loaded, delivered, empties collected and returned,
* stock moves once per trip, never per stop: a load-out transfer when the trip is loaded and, when it
  closes, the deliveries, the empties taken back and the return of what is left to the depot,
* vehicle stock for dispatchers.

Sale orders do not create their own transfers (``sale_stock`` is not used): the trips move the goods.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_container', 'h2o_dispatch', 'stock'],
    'data': [
        'security/h2o_stock_security.xml',
        'security/ir.access.csv',
        'data/h2o_stock_data.xml',
        'views/fleet_vehicle_views.xml',
        'views/h2o_route_views.xml',
        'views/h2o_trip_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_quant_views.xml',
        'views/h2o_stock_menus.xml',
    ],
    'demo': [
        'demo/h2o_stock_demo.xml',
    ],
    'installable': True,
}
