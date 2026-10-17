{
    'name': 'H2Open Driver App API',
    'version': '20.0.1.0.0',
    'category': 'H2Open',
    'summary': 'JSON API for the H2Open driver app: trips, stops, deliveries and positions',
    'description': """
H2Open driver app API
=====================
JSON endpoints under /h2o/api/v1/driver/ used by the Android driver app:

* the driver's trips of a day and their ordered stops, with everything needed at the door
  (address, phone, notes, products, bottle balance, amount due, coordinates),
* start and close a trip, deliver, fail or skip a stop, reorder the remaining stops,
* report the vehicle position,
* a push to the driver's phone when the dispatcher adds or removes a stop on a trip in progress.

Drivers only ever see and change their own trips.
""",
    'author': 'H2Open',
    'license': 'LGPL-3',
    'depends': ['h2o_dispatch', 'h2o_push'],
    'installable': True,
}
