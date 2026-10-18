from odoo import Command
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestZone(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.istanbul = cls.env.ref('base.state_tr_34')
        cls.kutahya = cls.env.ref('base.state_tr_43')
        cls.mon = cls.env.ref('h2o_base.weekday_mon')
        cls.thu = cls.env.ref('h2o_base.weekday_thu')
        cls.sat = cls.env.ref('h2o_base.weekday_sat')
        Zone = cls.env['h2o.zone']
        cls.zone_moda = Zone.create({
            'name': 'Test Moda', 'code': 'T-MODA', 'state_id': cls.istanbul.id,
            'district_names': 'Yeldeğirmeni, Rasimpaşa', 'zip_codes': '39710',
            'weekday_ids': [Command.set([cls.mon.id, cls.thu.id])],
        })
        cls.zone_center = Zone.create({
            'name': 'Test Center', 'code': 'T-CTR', 'state_id': cls.kutahya.id,
            'district_names': 'Hamidiye, Alipaşa', 'zip_codes': '49100',
        })
        cls.zones = cls.zone_moda | cls.zone_center

    def _partner(self, **vals):
        return self.env['res.partner'].new(vals)

    def test_match_zip_first(self):
        # the postal code wins over a district that points elsewhere
        partner = self._partner(zip='39710', city='Hamidiye')
        self.assertEqual(self.zones._h2o_match_partner(partner), self.zone_moda)

    def test_match_district_turkish_folding(self):
        for city, street2 in (('KADIKÖY', 'Rasimpasa Mah.'), ('', 'rasimpaşa mahallesi'), ('YELDEĞİRMENİ', '')):
            partner = self._partner(city=city, street2=street2, state_id=self.istanbul.id)
            self.assertEqual(self.zones._h2o_match_partner(partner), self.zone_moda, (city, street2))
        partner = self._partner(city='Merkez', street2='ALİPAŞA Mah.')
        self.assertEqual(self.zones._h2o_match_partner(partner), self.zone_center)

    def test_match_whole_words_only(self):
        partner = self._partner(city='Rasimpaşapark')
        self.assertFalse(self.zones._h2o_match_partner(partner))

    def test_match_respects_province(self):
        partner = self._partner(city='Hamidiye', state_id=self.istanbul.id)
        self.assertFalse(self.zones._h2o_match_partner(partner))

    def test_zone_set_on_create_and_address_write(self):
        partner = self.env['res.partner'].create({
            'name': 'Test Water Home', 'h2o_customer_type': 'home',
            'city': 'Kadıköy', 'street2': 'Rasimpaşa Mah.', 'state_id': self.istanbul.id,
        })
        self.assertEqual(partner.h2o_zone_id, self.zone_moda)
        # an existing zone is kept when the address changes
        partner.write({'city': 'Hamidiye', 'street2': False, 'state_id': self.kutahya.id})
        self.assertEqual(partner.h2o_zone_id, self.zone_moda)
        partner.h2o_zone_id = False
        partner.write({'street2': 'Alipaşa Mah.'})
        self.assertEqual(partner.h2o_zone_id, self.zone_center)

    def test_non_customer_gets_no_zone(self):
        partner = self.env['res.partner'].create({'name': 'Some Vendor', 'zip': '39710'})
        self.assertFalse(partner.h2o_zone_id)
        partner.h2o_customer_type = 'office'
        self.assertEqual(partner.h2o_zone_id, self.zone_moda)

    def test_delivery_address_of_customer_gets_zone(self):
        company = self.env['res.partner'].create({
            'name': 'Test Office', 'is_company': True, 'h2o_customer_type': 'office',
            'zip': '49100',
        })
        address = self.env['res.partner'].create({
            'name': 'Branch', 'parent_id': company.id, 'type': 'delivery', 'zip': '39710',
        })
        self.assertEqual(company.h2o_zone_id, self.zone_center)
        self.assertEqual(address.h2o_zone_id, self.zone_moda)

    def test_onchange_sets_zone(self):
        with Form(self.env['res.partner']) as form:
            form.name = 'Form Customer'
            form.h2o_customer_type = 'home'
            form.zip = '49100'
            self.assertEqual(form.h2o_zone_id, self.zone_center)

    def test_delivery_weekdays(self):
        company = self.env['res.partner'].create({
            'name': 'Days Office', 'is_company': True, 'h2o_customer_type': 'office', 'zip': '39710',
        })
        address = self.env['res.partner'].create({'name': 'Days Branch', 'parent_id': company.id, 'type': 'delivery'})
        self.assertEqual(company._h2o_delivery_weekdays(), self.mon | self.thu)
        self.assertEqual(address._h2o_delivery_weekdays(), self.mon | self.thu)
        company.h2o_weekday_ids = self.sat
        self.assertEqual(address._h2o_delivery_weekdays(), self.sat)
        address.h2o_weekday_ids = self.mon
        self.assertEqual(address._h2o_delivery_weekdays(), self.mon)

    def test_partner_count_and_assign(self):
        partner = self.env['res.partner'].create({'name': 'Late Customer', 'h2o_customer_type': 'home'})
        partner.write({'zip': '00000'})
        self.assertFalse(partner.h2o_zone_id)
        self.zone_center.zip_codes = '49100, 00000'
        self.zone_center.action_h2o_assign_partners()
        self.assertEqual(partner.h2o_zone_id, self.zone_center)
        self.assertEqual(self.zone_center.partner_count, 1)
        action = self.zone_center.action_view_partners()
        self.assertEqual(self.env['res.partner'].search(action['domain']), partner)

    def test_demo_customers_have_zones(self):
        demo = self.env.ref('h2o_customer.partner_home_mehmet', raise_if_not_found=False)
        if not demo:
            self.skipTest("demo data not installed")
        self.assertEqual(demo.h2o_zone_id, self.env.ref('h2o_customer.zone_uskudar'))
        self.assertEqual(self.env.ref('h2o_customer.partner_office_bogaz_kadikoy').h2o_zone_id,
                         self.env.ref('h2o_customer.zone_kadikoy'))
