from odoo.tests import TransactionCase, tagged

from odoo.addons.h2o_telephony.models.res_partner import h2o_normalize_phone


@tagged('post_install', '-at_install')
class TestPhoneLookup(TransactionCase):

    def test_normalize_turkish_numbers(self):
        for number in ('+90 532 123 45 67', '+905321234567', '0090 532 123 4567', '0 (532) 123-45-67',
                       '05321234567', '532 123 45 67', '905321234567'):
            self.assertEqual(h2o_normalize_phone(number), '5321234567', number)
        self.assertEqual(h2o_normalize_phone('0274 223 45 67'), '2742234567')
        self.assertEqual(h2o_normalize_phone('+44 20 7946 0958'), '442079460958')
        self.assertEqual(h2o_normalize_phone(False), '')

    def test_find_by_phone(self):
        Partner = self.env['res.partner']
        mobile = Partner.create({'name': 'Mobile Customer', 'phone': '0532 123 45 67'})
        landline = Partner.create({'name': 'Office Customer', 'phone': '+90 (274) 223 45 67'})
        Partner.create({'name': 'Same Ending', 'phone': '+90 533 123 45 67'})
        for number in ('+905321234567', '05321234567', '5321234567', '0090 532 1234567'):
            self.assertEqual(Partner._h2o_find_by_phone(number), mobile, number)
        self.assertEqual(Partner._h2o_find_by_phone('02742234567'), landline)
        self.assertFalse(Partner._h2o_find_by_phone('05551234567'))
        self.assertFalse(Partner._h2o_find_by_phone('201'), "Extensions never match a customer")
        self.assertFalse(Partner._h2o_find_by_phone(None))

    def test_company_wins_over_its_contacts(self):
        Partner = self.env['res.partner']
        company = Partner.create({'name': 'Su Ofis Ltd', 'is_company': True, 'phone': '0216 417 03 91'})
        Partner.create({'name': 'Reception', 'parent_id': company.id, 'phone': '+90 216 417 03 91'})
        self.assertEqual(Partner._h2o_find_by_phone('+902164170391'), company)

    def test_archived_partner_ignored(self):
        partner = self.env['res.partner'].create({'name': 'Gone', 'phone': '0532 999 88 77'})
        partner.action_archive()
        self.assertFalse(self.env['res.partner']._h2o_find_by_phone('05329998877'))
