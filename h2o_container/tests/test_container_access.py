from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestContainerAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = new_test_user(cls.env, login='h2o_cm_driver', groups='h2o_base.group_h2o_driver')
        cls.dispatcher = new_test_user(cls.env, login='h2o_cm_dispatcher', groups='h2o_base.group_h2o_dispatcher')
        cls.accountant = new_test_user(cls.env, login='h2o_cm_accountant', groups='h2o_base.group_h2o_accountant')
        cls.manager = new_test_user(cls.env, login='h2o_cm_manager', groups='h2o_base.group_h2o_manager')
        cls.bottle = cls.env.ref('h2o_container.product_bottle_19l')
        cls.customer = cls.env['res.partner'].create({'name': 'Access Home', 'h2o_customer_type': 'home'})
        cls.move = cls.env['h2o.container.move']._h2o_record(cls.customer, cls.bottle, qty_out=2)

    def test_driver_and_dispatcher_read_only(self):
        for user in (self.driver, self.dispatcher):
            Move = self.env['h2o.container.move'].with_user(user)
            self.assertEqual(Move.search([('partner_id', '=', self.customer.id)]), self.move)
            self.assertEqual(self.customer.with_user(user).h2o_bottle_balance, 2)
            self.env['h2o.container.balance'].with_user(user).search([])
            with self.assertRaises(AccessError):
                Move.create({'partner_id': self.customer.id, 'product_id': self.bottle.id, 'qty_in': 1})
            with self.assertRaises(AccessError):
                self.move.with_user(user).action_cancel()

    def test_driver_delivery_recorded_through_api(self):
        move = self.env['h2o.container.move'].with_user(self.driver)._h2o_record(self.customer, self.bottle, qty_in=1)
        self.assertEqual(move.env.uid, self.driver.id)
        self.assertEqual(move.create_uid, self.driver)
        self.assertEqual(move.qty_in, 1)

    def test_accountant_manages_adjustments(self):
        Move = self.env['h2o.container.move'].with_user(self.accountant)
        move = Move.create({'partner_id': self.customer.id, 'product_id': self.bottle.id,
                            'qty_in': 1, 'deposit_amount': -250.0})
        move.action_done()
        self.move.with_user(self.accountant).action_cancel()
        self.assertEqual(self.customer.with_user(self.accountant).h2o_bottle_balance, -1)
        move.action_cancel()
        move.action_draft()
        with self.assertRaises(AccessError):
            move.unlink()

    def test_manager_configures_water_products(self):
        Product = self.env['product.template'].with_user(self.manager)
        product = Product.create({'name': 'Test 1.5 L Water', 'h2o_product_kind': 'water_packaged', 'list_price': 15})
        product.list_price = 16
        with self.assertRaises(AccessError):
            Product.create({'name': 'Not water'})
        with self.assertRaises(AccessError):
            self.env['product.template'].with_user(self.dispatcher).create(
                {'name': 'Dispatcher water', 'h2o_product_kind': 'water_packaged'})
