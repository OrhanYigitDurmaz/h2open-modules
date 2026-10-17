from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestCustomerAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = new_test_user(cls.env, login='h2o_cust_driver', groups='h2o_base.group_h2o_driver')
        cls.accountant = new_test_user(cls.env, login='h2o_cust_accountant', groups='h2o_base.group_h2o_accountant')
        cls.dispatcher = new_test_user(cls.env, login='h2o_cust_dispatcher', groups='h2o_base.group_h2o_dispatcher')
        cls.manager = new_test_user(cls.env, login='h2o_cust_manager', groups='h2o_base.group_h2o_manager')
        cls.zone = cls.env['h2o.zone'].create({'name': 'Access Zone', 'zip_codes': '39999'})
        cls.customer = cls.env['res.partner'].create({
            'name': 'Access Customer', 'h2o_customer_type': 'home', 'zip': '39999',
            'h2o_delivery_notes': 'Ring twice',
        })

    def test_dispatcher_manages_customers_and_zones(self):
        Partner = self.env['res.partner'].with_user(self.dispatcher)
        partner = Partner.create({'name': 'New Customer', 'h2o_customer_type': 'office', 'zip': '39999'})
        self.assertEqual(partner.h2o_zone_id, self.zone)
        partner.write({'h2o_payment_mode': 'account'})
        zone = self.env['h2o.zone'].with_user(self.dispatcher).create({'name': 'Dispatcher Zone'})
        zone.write({'active': False})
        with self.assertRaises(AccessError):
            zone.unlink()
        self.env['h2o.zone'].with_user(self.manager).browse(zone.id).unlink()

    def test_driver_and_accountant_read_only(self):
        for user in (self.driver, self.accountant):
            customer = self.customer.with_user(user)
            self.assertEqual(customer.h2o_delivery_notes, 'Ring twice')
            self.assertEqual(customer.h2o_zone_id.with_user(user).name, 'Access Zone')
            with self.assertRaises(AccessError):
                customer.write({'h2o_delivery_notes': 'changed'})
            with self.assertRaises(AccessError):
                self.env['res.partner'].with_user(user).create({'name': 'Nope', 'h2o_customer_type': 'home'})
            with self.assertRaises(AccessError):
                self.env['h2o.zone'].with_user(user).create({'name': 'Nope'})
