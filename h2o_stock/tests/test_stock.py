from ast import literal_eval

from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.h2o_dispatch.tests.common import H2oDispatchCase


@tagged('post_install', '-at_install')
class TestStock(H2oDispatchCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.route.h2o_warehouse_id
        cls.stock = cls.warehouse.lot_stock_id
        cls.vehicle_location = cls.van.h2o_location_id
        # known warehouse stock, whatever the demo data holds
        Quant = cls.env['stock.quant']
        for product, qty in ((cls.water, 100), (cls.bottle, 50), (cls.water_5l, 40)):
            Quant._update_available_quantity(product, cls.stock, qty - product.with_context(
                location=cls.stock.id).qty_available)
        cls.order_1 = cls._order(cls.cash_customer, [(cls.water, 3), (cls.water_5l, 2)], empties=3)
        cls.order_2 = cls._order(cls.account_customer, [(cls.water, 4)], empties=2)

    def _qty(self, product, location):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('location_id', '=', location.id),
        ]).mapped('quantity'))

    def _assert_stock(self, location, expected):
        for product, qty in expected.items():
            self.assertEqual(self._qty(product, location), qty, f"{product.display_name} in {location.display_name}")

    def _line(self, trip, product):
        return trip.h2o_load_line_ids.filtered(lambda l: l.product_id == product)

    def _moved(self, picking):
        return {move.product_id: move.quantity for move in picking.move_ids}

    def test_setup(self):
        for product in (self.water, self.bottle, self.water_5l, self.env.ref('h2o_container.product_water_05l')):
            self.assertTrue(product.is_storable, product.display_name)
        self.assertFalse(self.deposit.is_storable)
        new_bottle = self.env['product.product'].create({'name': '10 L Bottle', 'h2o_product_kind': 'container'})
        self.assertTrue(new_bottle.is_storable)

        self.assertEqual(self.warehouse, self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1))
        self.assertRecordValues(self.vehicle_location, [{
            'usage': 'internal', 'h2o_vehicle_id': self.van.id, 'warehouse_id': self.warehouse.id,
        }])
        self.assertTrue(self.vehicle_location.complete_name.endswith('/Vehicles/06 TST 01'))
        self.van.license_plate = '06 TST 99'
        self.assertEqual(self.vehicle_location.name, '06 TST 99')
        self.assertFalse(self.driver_a.has_group('stock.group_stock_user'))
        self.assertTrue(self.dispatcher.has_group('stock.group_stock_user'))

    def test_load(self):
        trip = self._planned_trip()
        self.assertEqual(trip.h2o_warehouse_id, self.warehouse)
        self.assertRecordValues(self._line(trip, self.water), [{'qty_planned': 7, 'qty_loaded': 7}])
        self.assertRecordValues(self._line(trip, self.water_5l), [{'qty_planned': 2, 'qty_loaded': 2}])
        self.assertFalse(self._line(trip, self.deposit))
        self.assertFalse(trip.h2o_picking_ids)

        # the dispatcher loads a few spare bottles
        self._line(trip, self.water).with_user(self.dispatcher).qty_loaded = 10
        trip.with_user(self.driver_a).action_load()
        self.assertEqual(trip.load_qty, 10)
        load = trip.h2o_picking_ids
        self.assertRecordValues(load, [{
            'h2o_trip_role': 'load', 'state': 'done', 'origin': trip.name,
            'location_id': self.stock.id, 'location_dest_id': self.vehicle_location.id,
        }])
        self.assertEqual(self._moved(load), {self.water: 10, self.water_5l: 2})
        self._assert_stock(self.stock, {self.water: 90, self.water_5l: 38})
        self._assert_stock(self.vehicle_location, {self.water: 10, self.water_5l: 2})

        action = trip.with_user(self.dispatcher).action_view_pickings()
        self.assertEqual(self.env['stock.picking'].search(action['domain']), load)
        self.assertEqual(trip.h2o_picking_count, 1)

    def test_close_as_driver(self):
        trip = self._planned_trip().with_user(self.driver_a)
        trip.action_start()
        stop_1, stop_2 = trip.stop_ids
        stop_1.action_deliver({'empties_collected': 2})
        stop_2.action_deliver()
        trip.action_close()

        self.assertRecordValues(trip, [{'state': 'closed', 'returned_full_qty': 0, 'returned_empty_qty': 4}])
        self.assertRecordValues(self._line(trip, self.water), [{
            'qty_loaded': 7, 'qty_delivered': 7, 'qty_collected': 0, 'qty_returned': 0,
        }])
        self.assertRecordValues(self._line(trip, self.bottle), [{
            'qty_planned': 0, 'qty_loaded': 0, 'qty_collected': 4, 'qty_returned': 4,
        }])
        pickings = trip.sudo().h2o_picking_ids
        self.assertEqual(pickings.mapped('state'), ['done'] * 4)
        by_role = {picking.h2o_trip_role: picking for picking in pickings}
        customers = by_role['delivery'].location_dest_id
        self.assertEqual(customers.usage, 'customer')
        self.assertEqual(self._moved(by_role['delivery']), {self.water: 7, self.water_5l: 2})
        self.assertEqual(self._moved(by_role['empties']), {self.bottle: 4})
        self.assertEqual(by_role['empties'].location_dest_id, self.vehicle_location)
        self.assertEqual(self._moved(by_role['return']), {self.bottle: 4})
        self.assertEqual(by_role['return'].location_dest_id, self.stock)

        self._assert_stock(self.vehicle_location, {self.water: 0, self.water_5l: 0, self.bottle: 0})
        self._assert_stock(self.stock, {self.water: 93, self.water_5l: 38, self.bottle: 54})

    def test_failed_stop_returns_bottles(self):
        trip = self._started_trip()
        stop_1, stop_2 = trip.stop_ids
        stop_1.with_user(self.driver_a).action_deliver()
        stop_2.with_user(self.driver_a).action_fail('not_home')
        trip.with_user(self.driver_a).action_close()

        self.assertEqual(trip.returned_full_qty, 4)
        self.assertRecordValues(self._line(trip, self.water), [{
            'qty_loaded': 7, 'qty_delivered': 3, 'qty_returned': 4,
        }])
        ret = trip.h2o_picking_ids.filtered(lambda p: p.h2o_trip_role == 'return')
        self.assertEqual(self._moved(ret), {self.water: 4, self.bottle: 3})
        self._assert_stock(self.vehicle_location, {self.water: 0, self.water_5l: 0, self.bottle: 0})
        self._assert_stock(self.stock, {self.water: 97, self.water_5l: 38, self.bottle: 53})
        self.assertEqual(self.order_2.h2o_delivery_state, 'to_plan')

    def test_deliver_more_than_loaded(self):
        trip = self._planned_trip()
        self._line(trip, self.water).qty_loaded = 5
        trip.with_user(self.driver_a).action_start()
        trip.stop_ids.with_user(self.driver_a).action_deliver()
        trip.with_user(self.driver_a).action_close()

        self.assertEqual(trip.state, 'closed')
        self.assertRecordValues(self._line(trip, self.water), [{
            'qty_loaded': 5, 'qty_delivered': 7, 'qty_returned': 0,
        }])
        # the vehicle shows the bottles that were never recorded as loaded
        self._assert_stock(self.vehicle_location, {self.water: -2, self.bottle: 0})
        self._assert_stock(self.stock, {self.water: 95})
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_stock.h2o_vehicle_stock_action')
        quants = self.env['stock.quant'].search(literal_eval(action['domain']))
        self.assertIn(self.water, quants.filtered(lambda q: q.location_id == self.vehicle_location).product_id)

    def test_replanning_does_not_duplicate(self):
        trip = self._planned_trip()
        self.assertFalse(self._planned_trip())
        order_3 = self._order(self.cash_customer, [(self.water, 2)])
        self.assertEqual(self._planned_trip(), trip)
        self.assertEqual(len(trip.h2o_load_line_ids), 2)
        self.assertRecordValues(self._line(trip, self.water), [{'qty_planned': 9, 'qty_loaded': 9}])
        self.assertFalse(trip.h2o_picking_ids)

        trip.action_load()
        trip._h2o_on_loaded()
        self.assertEqual(trip.h2o_picking_ids.mapped('h2o_trip_role'), ['load'])

        trip.action_start()
        trip.stop_ids.filtered(lambda s: s.order_id == order_3).action_deliver()
        (trip.stop_ids - trip.stop_ids.filtered(lambda s: s.order_id == order_3)).action_skip()
        trip.action_close()
        trip._h2o_on_closed()
        self.assertEqual(sorted(trip.h2o_picking_ids.mapped('h2o_trip_role')), ['delivery', 'load', 'return'])
        self._assert_stock(self.vehicle_location, {self.water: 0, self.water_5l: 0})
        self._assert_stock(self.stock, {self.water: 98, self.water_5l: 40})

    def test_cancel_unloads(self):
        trip = self._started_trip()
        trip.with_user(self.dispatcher).action_cancel()
        self.assertEqual(sorted(trip.h2o_picking_ids.mapped('h2o_trip_role')), ['load', 'return'])
        self._assert_stock(self.vehicle_location, {self.water: 0, self.water_5l: 0})
        self._assert_stock(self.stock, {self.water: 100, self.water_5l: 40})

        trip.with_user(self.dispatcher).action_reset_planned()
        self.assertEqual(self._planned_trip(), trip)
        trip.action_load()
        self.assertEqual(sorted(trip.h2o_picking_ids.mapped('h2o_trip_role')), ['load', 'load', 'return'])
        self.assertEqual(trip._h2o_current_pickings().mapped('h2o_trip_role'), ['load'])
        self._assert_stock(self.vehicle_location, {self.water: 7, self.water_5l: 2})

    def test_load_line_access(self):
        trip = self._planned_trip()
        lines = trip.h2o_load_line_ids
        self.assertEqual(lines.with_user(self.driver_a).read(['qty_planned'])[0]['qty_planned'], lines[0].qty_planned)
        with self.assertRaises(AccessError):
            lines.with_user(self.driver_b).read(['qty_planned'])
        with self.assertRaises(AccessError):
            lines.with_user(self.driver_a).write({'qty_loaded': 1})
        lines.with_user(self.dispatcher).write({'qty_loaded': 1})
