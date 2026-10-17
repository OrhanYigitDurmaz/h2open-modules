from datetime import date

from odoo.exceptions import UserError
from odoo.tests import Form, new_test_user, tagged

from .common import H2oOrderCase


@tagged('post_install', '-at_install')
class TestQuickOrder(H2oOrderCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dispatcher = new_test_user(cls.env, login='h2o_quick_dispatcher', groups='h2o_base.group_h2o_dispatcher')
        cls.address = cls.env['res.partner'].create({
            'name': 'Second home', 'parent_id': cls.customer.id, 'type': 'delivery',
            'h2o_delivery_notes': 'Garden gate',
        })

    def test_phone_order_flow(self):
        # the customer holds 1 bottle: the first returnable bottle is a swap
        self.env['h2o.container.move']._h2o_record(self.customer, self.bottle, qty_out=1)
        wizard_form = Form(self.env['h2o.quick.order'].with_user(self.dispatcher))
        wizard_form.partner_id = self.customer
        self.assertEqual(wizard_form.partner_shipping_id, self.address)
        self.assertEqual(wizard_form.delivery_notes, 'Garden gate')
        self.assertEqual(len(wizard_form.line_ids), 1)
        with wizard_form.line_ids.edit(0) as line:
            self.assertEqual(line.product_id, self.water)
            line.qty = 3
        self.assertEqual(wizard_form.empties_expected, 1)
        with wizard_form.line_ids.new() as line:
            line.product_id = self.water_5l
            line.product_uom_id = self.env.ref('h2o_container.uom_pack_4')
            line.qty = 2
        wizard_form.delivery_date = date(2030, 1, 7)
        wizard_form.time_window = 'morning'
        wizard_form.note = 'Call before'
        wizard = wizard_form.save()
        action = wizard.action_create_order()

        order = self.env['sale.order'].browse(action['res_id'])
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.partner_shipping_id, self.address)
        self.assertEqual(order.h2o_channel, 'phone')
        self.assertEqual(order.h2o_delivery_date, date(2030, 1, 7))
        self.assertEqual(order.h2o_time_window, 'morning')
        self.assertEqual(order.h2o_empties_expected, 1)
        self.assertEqual(self._deposit_qty(order), (2, 1))
        pack_line = order.order_line.filtered(lambda line: line.product_id == self.water_5l)
        self.assertEqual(pack_line.product_uom_id, self.env.ref('h2o_container.uom_pack_4'))
        self.assertEqual(pack_line.product_uom_qty, 2)

        # the next phone order repeats the water of the last one
        repeat = Form(self.env['h2o.quick.order'].with_user(self.dispatcher))
        repeat.partner_id = self.customer
        self.assertEqual(
            sorted((line.product_id.id, line.qty) for line in repeat.save().line_ids),
            sorted([(self.water.id, 3.0), (self.water_5l.id, 2.0)]),
        )

    def test_empty_order_refused(self):
        wizard = self.env['h2o.quick.order'].create({'partner_id': self.customer.id})
        wizard.line_ids.qty = 0
        with self.assertRaises(UserError):
            wizard.action_create_order()
