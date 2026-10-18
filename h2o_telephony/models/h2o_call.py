from odoo import api, fields, models

CALL_EVENTS = ('ring', 'answer', 'hangup')


class H2oCall(models.Model):
    _name = 'h2o.call'
    _description = 'Phone Call'
    _order = 'start desc, id desc'

    direction = fields.Selection([
        ('inbound', "Inbound"),
        ('outbound', "Outbound"),
        ('internal', "Internal"),
    ], required=True, default='inbound')
    caller_number = fields.Char(string="Caller")
    called_number = fields.Char(string="Called")
    partner_id = fields.Many2one('res.partner', string="Customer", index='btree_not_null', ondelete='set null')
    user_id = fields.Many2one('res.users', string="Answered By", ondelete='set null')
    start = fields.Datetime(required=True, default=fields.Datetime.now)
    answer = fields.Datetime(string="Answered")
    end = fields.Datetime(string="Ended")
    duration = fields.Integer(string="Duration (s)", compute='_compute_duration', store=True,
                              help="Talk time in seconds, from answer to hang-up.")
    state = fields.Selection([
        ('ringing', "Ringing"),
        ('answered', "Answered"),
        ('missed', "Missed"),
        ('ended', "Ended"),
    ], required=True, default='ringing')
    asterisk_uniqueid = fields.Char(string="Asterisk Unique ID", required=True, readonly=True)

    _asterisk_uniqueid_unique = models.Constraint('UNIQUE(asterisk_uniqueid)', 'This Asterisk call is already logged.')

    @api.depends('answer', 'end')
    def _compute_duration(self):
        for call in self:
            if call.answer and call.end:
                call.duration = int((call.end - call.answer).total_seconds())
            else:
                call.duration = 0

    @api.depends('partner_id', 'caller_number', 'called_number', 'direction')
    def _compute_display_name(self):
        for call in self:
            number = call.called_number if call.direction == 'outbound' else call.caller_number
            call.display_name = call.partner_id.display_name or number or self.env._("Unknown number")

    @api.model
    def _h2o_from_event(self, uniqueid, event, caller=None, called=None, direction='inbound', extension=None):
        """Create or update the call of an Asterisk event and return it.

        :param str event: ``ring``, ``answer`` or ``hangup``
        :param str extension: SIP extension that answered (``answer`` event)

        Events are idempotent: Asterisk may repeat them or skip ``ring``.
        """
        call = self.search([('asterisk_uniqueid', '=', uniqueid)], limit=1)
        if not call:
            customer_number = called if direction == 'outbound' else caller
            call = self.create({
                'asterisk_uniqueid': uniqueid,
                'direction': direction,
                'caller_number': caller,
                'called_number': called,
                'partner_id': self.env['res.partner']._h2o_find_by_phone(customer_number).id,
            })
            if event == 'ring' and direction == 'inbound':
                call._h2o_notify_dispatchers()

        now = fields.Datetime.now()
        if event == 'answer' and call.state == 'ringing':
            user = self.env['res.users']
            if extension:
                user = self.env['h2o.sip.account'].search([('extension', '=', extension)], limit=1).user_id
            call.write({'state': 'answered', 'answer': now, 'user_id': user.id})
        elif event == 'hangup' and call.state in ('ringing', 'answered'):
            call.write({'state': 'ended' if call.answer else 'missed', 'end': now})
        return call

    def _h2o_notify_dispatchers(self):
        """Pop up the incoming call in the web client of every dispatcher."""
        self.ensure_one()
        dispatchers = self.env.ref('h2o_base.group_h2o_dispatcher').all_user_ids
        dispatchers._bus_send('h2o_telephony/incoming_call', {
            'call_id': self.id,
            'number': self.caller_number or '',
            'name': self.partner_id.display_name or '',
            'partner_id': self.partner_id.id,
        })
