from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .common import H2oTelephonyCommon


@tagged('post_install', '-at_install')
class TestCall(H2oTelephonyCommon, TransactionCase):

    def _incoming_call_notifications(self):
        return [
            (channel, payload) for channel, type_, payload in self.env.cr.precommit.data.get('bus.bus.values', [])
            if type_ == 'h2o_telephony/incoming_call'
        ]

    def test_answered_call(self):
        Call = self.env['h2o.call']
        start = fields.Datetime.now()
        call = Call._h2o_from_event('1700000000.1', 'ring', caller='05321234567', called='02742234567')
        self.assertRecordValues(call, [{
            'direction': 'inbound', 'state': 'ringing', 'partner_id': self.customer.id,
            'caller_number': '05321234567', 'called_number': '02742234567',
        }])
        self.assertEqual(call.display_name, self.customer.display_name)

        notifications = self._incoming_call_notifications()
        notified_users = {channel[2] for channel, payload in notifications if channel[1] == 'res.users'}
        self.assertIn(self.dispatcher.id, notified_users)
        self.assertNotIn(self.driver.id, notified_users)
        self.assertEqual(notifications[0][1], {
            'call_id': call.id, 'number': '05321234567', 'name': 'Ayşe Yılmaz', 'partner_id': self.customer.id,
        })

        # Repeated ring: same call, no second pop-up.
        count = len(notifications)
        self.assertEqual(Call._h2o_from_event('1700000000.1', 'ring', caller='05321234567'), call)
        self.assertEqual(len(self._incoming_call_notifications()), count)

        with patch.object(fields.Datetime, 'now', return_value=start + timedelta(seconds=5)):
            Call._h2o_from_event('1700000000.1', 'answer', extension='201')
        self.assertRecordValues(call, [{'state': 'answered', 'user_id': self.driver.id}])
        with patch.object(fields.Datetime, 'now', return_value=start + timedelta(seconds=65)):
            Call._h2o_from_event('1700000000.1', 'hangup')
        self.assertRecordValues(call, [{'state': 'ended', 'duration': 60}])

        # A late duplicate hangup changes nothing.
        Call._h2o_from_event('1700000000.1', 'hangup')
        self.assertEqual(call.duration, 60)

    def test_missed_call_unknown_number(self):
        call = self.env['h2o.call']._h2o_from_event('1700000000.2', 'ring', caller='+90 555 000 11 22')
        self.assertFalse(call.partner_id)
        self.assertEqual(call.display_name, '+90 555 000 11 22')
        self.assertEqual(self._incoming_call_notifications()[0][1]['name'], '')
        self.env['h2o.call']._h2o_from_event('1700000000.2', 'hangup')
        self.assertRecordValues(call, [{'state': 'missed', 'duration': 0}])

    def test_outbound_call_matches_called_number(self):
        call = self.env['h2o.call']._h2o_from_event(
            '1700000000.3', 'answer', caller='201', called='0532 123 45 67', direction='outbound', extension='201')
        self.assertRecordValues(call, [{'partner_id': self.customer.id, 'state': 'answered',
                                        'user_id': self.driver.id}])
        self.assertFalse(self._incoming_call_notifications())

    def test_dispatcher_access(self):
        call = self.env['h2o.call']._h2o_from_event('1700000000.4', 'ring', caller='05321234567')
        self.assertEqual(self.env['h2o.call'].with_user(self.dispatcher).search([('id', '=', call.id)]), call)
        self.assertFalse(self.env['h2o.call'].with_user(self.driver).has_access('read'))
