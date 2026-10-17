from odoo.tests import tagged

from .common import H2oOrderCase


@tagged('post_install', '-at_install')
class TestPricelist(H2oOrderCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Pricelist = cls.env['product.pricelist']
        cls.pl_home = Pricelist.create({'name': 'T Home'})
        cls.pl_office = Pricelist.create({'name': 'T Office', 'item_ids': [(0, 0, {
            'applied_on': '1_product', 'product_tmpl_id': cls.water.product_tmpl_id.id,
            'compute_price': 'fixed', 'fixed_price': 99.0,
        })]})
        cls.env.company.write({
            'h2o_pricelist_home_id': cls.pl_home.id,
            'h2o_pricelist_office_id': cls.pl_office.id,
            'h2o_pricelist_reseller_id': False,
        })

    def test_pricelist_from_customer_type(self):
        partner = self.env['res.partner'].create({'name': 'Typed Office', 'h2o_customer_type': 'office'})
        self.assertEqual(partner.property_product_pricelist, self.pl_office)
        partner.h2o_customer_type = 'home'
        self.assertEqual(partner.property_product_pricelist, self.pl_home)
        # no pricelist configured for resellers: keep the current one
        partner.h2o_customer_type = 'reseller'
        self.assertEqual(partner.property_product_pricelist, self.pl_home)

    def test_order_uses_type_price(self):
        partner = self.env['res.partner'].create({'name': 'Priced Office', 'h2o_customer_type': 'office'})
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': self.water.id, 'product_uom_qty': 2})],
        })
        self.assertEqual(order.pricelist_id, self.pl_office)
        self.assertEqual(order.order_line.price_unit, 99.0)
