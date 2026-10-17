from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWeekday(TransactionCase):

    def test_seven_weekdays(self):
        self.assertEqual(self.env['h2o.weekday'].search_count([]), 7)

    def test_from_date(self):
        # 2026-10-19 is a Monday
        self.assertEqual(self.env['h2o.weekday']._h2o_from_date(date(2026, 10, 19)),
                         self.env.ref('h2o_base.weekday_mon'))
