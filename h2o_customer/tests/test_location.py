from unittest.mock import patch

import requests

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.h2o_customer.models import res_partner
from odoo.addons.h2o_customer.models.res_partner import h2o_parse_location


class FakeResponse:

    def __init__(self, status=200, json=None, location=None):
        self.status_code = status
        self._json = json
        self.headers = {'Location': location} if location else {}
        self.is_redirect = bool(location)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(self.status_code)


@tagged('post_install', '-at_install')
class TestLocation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        # No waiting between the mocked OpenStreetMap searches.
        cls.startClassPatcher(patch.object(res_partner, 'NOMINATIM_INTERVAL', 0))

    def test_parse_location(self):
        cases = {
            '41.0329, 28.9784': [41.0329, 28.9784],
            ' 41.0329;28.9784 ': [41.0329, 28.9784],
            'geo:39.92,32.85?z=17': [39.92, 32.85],
            'https://www.google.com/maps/@41.0082,28.9784,17z': [41.0082, 28.9784],
            # The place pin wins over the map center.
            'https://www.google.com/maps/place/X/@41.00,28.90,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!3d41.0123!4d28.9456':
                [41.0123, 28.9456],
            'https://maps.google.com/?q=39.75,30.48': [39.75, 30.48],
            'https://www.google.com/maps/dir/?api=1&destination=39.75%2C30.48': [39.75, 30.48],
        }
        for text, point in cases.items():
            with self.subTest(text=text):
                self.assertEqual(h2o_parse_location(text), point)
        for text in ('', 'Moda Cd. 12 34', '12 34', '91.5, 28.9', 'https://maps.app.goo.gl/abc', '0.0, 0.0'):
            with self.subTest(text=text):
                self.assertIsNone(h2o_parse_location(text))

    def test_has_location(self):
        partner = self.Partner.create({'name': 'Pinned', 'h2o_customer_type': 'home'})
        self.assertFalse(partner.h2o_has_location)
        partner.write({'partner_latitude': 41.0, 'partner_longitude': 29.0})
        self.assertTrue(partner.h2o_has_location)
        self.assertIn(partner, self.Partner.search([('h2o_has_location', '=', True)]))

    def test_locate_pasted_point(self):
        with patch.object(requests, 'get') as get:
            self.assertEqual(self.Partner.h2o_locate('41.03, 28.97'), {'point': [41.03, 28.97]})
        get.assert_not_called()

    def test_locate_short_link(self):
        long_url = 'https://www.google.com/maps/place/Moda/@40.98,29.02,17z/data=!3d40.9812!4d29.0251'
        responses = {
            'https://maps.app.goo.gl/abc': FakeResponse(302, location='https://goo.gl/maps/xyz'),
            'https://goo.gl/maps/xyz': FakeResponse(301, location=long_url),
        }
        with patch.object(requests, 'get', side_effect=lambda url, **kw: responses[url]) as get:
            self.assertEqual(self.Partner.h2o_locate('https://maps.app.goo.gl/abc'), {'point': [40.9812, 29.0251]})
        self.assertEqual(get.call_count, 2)

    def test_locate_does_not_follow_other_hosts(self):
        responses = {'https://maps.app.goo.gl/abc': FakeResponse(302, location='https://evil.example/@1.5,2.5')}
        with patch.object(requests, 'get', side_effect=lambda url, **kw: responses[url]) as get:
            # The redirect target is parsed, never fetched.
            self.assertEqual(self.Partner.h2o_locate('https://maps.app.goo.gl/abc'), {'point': [1.5, 2.5]})
        self.assertEqual(get.call_count, 1)
        with patch.object(requests, 'get') as get, \
                patch.object(type(self.Partner), '_h2o_nominatim_search', return_value=[]):
            self.assertEqual(self.Partner.h2o_locate('https://intranet.local/x'), {'results': []})
        get.assert_not_called()

    def test_locate_search(self):
        places = [
            {'display_name': 'Moda Caddesi, Kadıköy, İstanbul', 'lat': '40.9839', 'lon': '29.0262'},
            {'display_name': 'No coordinates'},
        ]
        with patch.object(requests, 'get', return_value=FakeResponse(json=places)) as get:
            found = self.Partner.h2o_locate('Moda Caddesi Kadıköy')
        self.assertEqual(found, {'results': [{'name': 'Moda Caddesi, Kadıköy, İstanbul', 'lat': 40.9839, 'lng': 29.0262}]})
        params = get.call_args.kwargs['params']
        self.assertEqual(params['countrycodes'], 'tr')
        self.assertTrue(get.call_args.kwargs['headers']['User-Agent'].startswith('H2Open'))

        with patch.object(requests, 'get', side_effect=requests.ConnectionError), self.assertRaises(UserError):
            self.Partner.h2o_locate('Moda Caddesi')

    def test_locate_employees_only(self):
        portal = new_test_user(self.env, login='h2o_loc_portal', groups='base.group_portal')
        with self.assertRaises(AccessError):
            self.Partner.with_user(portal).h2o_locate('41.0, 29.0')
