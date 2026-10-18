from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestContainerLedger(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Move = cls.env['h2o.container.move']
        cls.bottle = cls.env.ref('h2o_container.product_bottle_19l')
        cls.water = cls.env.ref('h2o_container.product_water_19l')
        cls.water_5l = cls.env.ref('h2o_container.product_water_5l')
        cls.other_bottle = cls.env['product.product'].create({
            'name': 'Test 10 L Bottle', 'h2o_product_kind': 'container', 'type': 'consu',
        })
        cls.customer = cls.env['res.partner'].create({
            'name': 'Ledger Office', 'is_company': True, 'h2o_customer_type': 'office',
        })
        cls.address = cls.env['res.partner'].create({
            'name': 'Ledger Branch', 'parent_id': cls.customer.id, 'type': 'delivery',
        })

    def test_product_data(self):
        self.assertEqual(self.water.h2o_container_product_id, self.bottle)
        self.assertEqual(self.bottle.h2o_deposit_product_id, self.env.ref('h2o_container.product_deposit_19l'))
        self.assertEqual(self.bottle.h2o_deposit_product_id.type, 'service')
        self.assertEqual(self.water_5l.h2o_product_kind, 'water_packaged')
        self.assertIn(self.env.ref('h2o_container.uom_pack_4'), self.water_5l.uom_ids)
        with self.assertRaises(ValidationError):
            self.water_5l.h2o_container_product_id = self.bottle

    def test_record_and_balances(self):
        move = self.Move._h2o_record(self.address, self.bottle, qty_out=3, deposit_amount=750.0,
                                     origin='S0001', origin_ref=self.customer)
        self.assertEqual(move.state, 'done')
        self.assertTrue(move.name.startswith('CM/'))
        self.assertEqual(move.partner_id, self.customer)
        self.assertEqual(move.address_id, self.address)
        self.assertEqual(move.origin_ref, self.customer)
        self.assertEqual(move.source, 'delivery')

        self.Move._h2o_record(self.customer, self.bottle, qty_out=2, qty_in=4, deposit_amount=-500.0)
        self.Move._h2o_record(self.customer, self.other_bottle, qty_out=5)
        # draft entries do not count
        self.Move.create({'partner_id': self.customer.id, 'product_id': self.bottle.id, 'qty_out': 100})

        for partner in (self.customer, self.address):
            partner.invalidate_recordset()
            self.assertEqual(partner.h2o_bottle_balance, 6)
            self.assertEqual(partner.h2o_deposit_balance, 250.0)
            self.assertEqual(partner.h2o_container_move_count, 3)
        self.assertEqual(self.address._h2o_bottle_balance_by_product(), {self.bottle: 1, self.other_bottle: 5})

        balances = self.env['h2o.container.balance'].search([('partner_id', '=', self.customer.id)])
        self.assertEqual(
            {(b.product_id, b.qty, b.deposit_amount) for b in balances},
            {(self.bottle, 1, 250.0), (self.other_bottle, 5, 0.0)},
        )

        action = self.address.action_h2o_view_container_moves()
        self.assertEqual(self.Move.search(action['domain'] + [('state', '=', 'done')]).partner_id, self.customer)

    def test_zero_balance_left_out(self):
        self.Move._h2o_record(self.customer, self.bottle, qty_out=2)
        self.Move._h2o_record(self.customer, self.bottle, qty_in=2)
        self.assertEqual(self.customer._h2o_bottle_balance_by_product(), {})

    def test_balance_view_with_unset_quantities(self):
        """A move created with only one quantity (opening balance, import) stores NULL for the other."""
        self.Move.create({'partner_id': self.customer.id, 'product_id': self.bottle.id, 'qty_out': 3,
                          'source': 'opening'}).action_done()
        self.Move.create({'partner_id': self.customer.id, 'product_id': self.bottle.id, 'qty_in': 1,
                          'source': 'adjustment'}).action_done()
        self.env.flush_all()
        balance = self.env['h2o.container.balance'].search([('partner_id', '=', self.customer.id)])
        self.assertEqual((balance.qty, balance.qty_out, balance.qty_in), (2, 3, 1))

    def test_cancel_and_protection(self):
        move = self.Move._h2o_record(self.customer, self.bottle, qty_out=2)
        with self.assertRaises(UserError):
            move.qty_out = 3
        with self.assertRaises(UserError):
            move.unlink()
        with self.assertRaises(UserError):
            move.action_draft()
        move.note = 'notes stay editable'
        move.action_cancel()
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.h2o_bottle_balance, 0)
        move.action_draft()
        move.qty_out = 3
        move.action_done()
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.h2o_bottle_balance, 3)
        with self.assertRaises(UserError):
            move.action_done()

    def test_constraints(self):
        with self.assertRaises(ValidationError):
            self.Move.create({'partner_id': self.customer.id, 'product_id': self.water.id, 'qty_out': 1})
        with self.assertRaises(ValidationError):
            self.Move.create({'partner_id': self.customer.id, 'product_id': self.bottle.id})
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.Move.create({'partner_id': self.customer.id, 'product_id': self.bottle.id, 'qty_in': -1})

    def test_manual_entry_normalizes_partner(self):
        move = self.Move.create({'partner_id': self.address.id, 'product_id': self.bottle.id, 'qty_in': 1})
        self.assertEqual(move.partner_id, self.customer)
        self.assertEqual(move.address_id, self.address)
        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.source, 'adjustment')
