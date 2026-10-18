from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import freeze_time, tagged

from odoo.addons.h2o_subscription.models.h2o_subscription import h2o_following_date

from .common import H2oSubscriptionCase


@tagged('post_install', '-at_install')
class TestSubscriptionDates(H2oSubscriptionCase):

    def test_following_date(self):
        cases = [
            # (date, frequency, expected)
            (date(2026, 10, 26), 'weekly', date(2026, 11, 2)),     # Monday, across a month end
            (date(2026, 12, 31), 'weekly', date(2027, 1, 7)),      # Thursday, across a year end
            (date(2026, 12, 24), 'biweekly', date(2027, 1, 7)),
            (date(2026, 10, 12), 'monthly', date(2026, 11, 9)),    # 2nd Monday -> 2nd Monday
            (date(2026, 10, 1), 'monthly', date(2026, 11, 5)),     # 1st Thursday -> 1st Thursday
            (date(2026, 12, 7), 'monthly', date(2027, 1, 4)),      # 1st Monday, into the next year
            (date(2026, 10, 29), 'monthly', date(2026, 11, 26)),   # 5th Thursday -> last Thursday
            (date(2027, 1, 29), 'monthly', date(2027, 2, 26)),     # 5th Friday -> last Friday of February
            (date(2026, 11, 26), 'monthly', date(2026, 12, 24)),   # 4th Thursday -> 4th Thursday
        ]
        for day, frequency, expected in cases:
            result = h2o_following_date(day, frequency)
            self.assertEqual(result, expected, (day, frequency))
            self.assertEqual(result.weekday(), day.weekday())

    def test_activation_first_date(self):
        # 2026-10-19 is a Monday; Istanbul is UTC+3, cut-off 16:00; delivery days Monday and Thursday
        with freeze_time('2026-10-19 10:00'):
            subscription = self.env['h2o.subscription'].create({
                'partner_id': self.customer.id,
                'line_ids': [Command.create({'product_id': self.water.id, 'qty': 2})],
            })
            self.assertEqual(subscription.weekday_id, self.mon, "defaults to the next delivery day")
            self.assertFalse(subscription.next_date)
            subscription.action_activate()
            self.assertEqual(subscription.state, 'active')
            self.assertEqual(subscription.next_date, date(2026, 10, 19))
            tuesday = self._subscription(weekday_id=self.env.ref('h2o_base.weekday_tue').id)
            tuesday.action_activate()
            self.assertEqual(tuesday.next_date, date(2026, 10, 20))
        with freeze_time('2026-10-19 14:00'):  # 17:00, after the cut-off
            late = self._subscription()
            late.action_activate()
            self.assertEqual(late.next_date, date(2026, 10, 26))
            planned = self._subscription(next_date=date(2026, 11, 9))
            planned.action_activate()
            self.assertEqual(planned.next_date, date(2026, 11, 9), "a future date set by hand is kept")

    def test_activation_checks(self):
        with self.assertRaises(UserError):
            self._subscription(line_ids=[]).action_activate()
        with self.assertRaises(ValidationError):
            self._subscription(next_date=date(2026, 10, 20))  # a Tuesday for a Monday subscription

    def test_resume_restarts_after_pause(self):
        with freeze_time('2026-10-19 10:00'):
            subscription = self._subscription()
            subscription.action_activate()
            subscription.action_pause()
            self.assertEqual(subscription.state, 'paused')
            with self.assertRaises(UserError):
                subscription.action_pause()
        with freeze_time('2026-11-04 10:00'):  # Wednesday, the paused date is gone
            subscription.action_resume()
            self.assertEqual(subscription.state, 'active')
            self.assertEqual(subscription.next_date, date(2026, 11, 9))
            subscription.action_close()
            self.assertEqual(subscription.state, 'closed')
            with self.assertRaises(UserError):
                subscription.action_resume()
