import logging
import secrets
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

ARI_TIMEOUT = 10
# Names of the Asterisk objects the driver endpoints rely on (see the module description).
WSS_TRANSPORT = 'transport-wss'
DRIVER_CONTEXT = 'h2o-drivers'
# Asterisk is reached through WireGuard and the app through the VPS: no STUN/TURN.
ICE_SERVERS = []


class H2oSipAccount(models.Model):
    _name = 'h2o.sip.account'
    _description = 'SIP Account'
    _order = 'extension'
    _rec_name = 'extension'

    user_id = fields.Many2one('res.users', string="User", required=True, index=True, ondelete='cascade')
    extension = fields.Char(required=True, help="SIP user name and internal number of the user, e.g. 201.")
    active = fields.Boolean(default=True)
    password_expires_at = fields.Datetime(
        string="Credentials Expire",
        readonly=True,
        copy=False,
        help="The password is generated when the driver app signs in and is only known by the app "
             "and Asterisk. Asterisk forgets it at this time.",
    )

    _user_unique = models.Constraint('UNIQUE(user_id)', 'A user can only have one SIP account.')
    _extension_unique = models.Constraint('UNIQUE(extension)', 'This extension is already used.')

    @api.depends('extension', 'user_id.name')
    def _compute_display_name(self):
        for account in self:
            account.display_name = "%s - %s" % (account.extension, account.user_id.name)

    @api.constrains('extension')
    def _check_extension(self):
        for account in self:
            if not account.extension.isdigit():
                raise ValidationError(self.env._("The extension must only contain digits."))

    def action_h2o_revoke(self):
        self._h2o_revoke()

    # ------------------------------------------------------------
    # Asterisk REST Interface
    # ------------------------------------------------------------

    @api.model
    def _h2o_ari_config(self):
        params = self.env['ir.config_parameter'].sudo()
        url = params.get_str('h2o_telephony.ari_url')
        if not url:
            raise UserError(self.env._("The Asterisk ARI URL is not configured."))
        auth = (params.get_str('h2o_telephony.ari_user'), params.get_str('h2o_telephony.ari_password'))
        return url.rstrip('/'), auth

    def _h2o_ari_request(self, method, object_type, fields_values=None):
        """Create, update (PUT) or delete (DELETE) a dynamic PJSIP object named after the extension."""
        self.ensure_one()
        url, auth = self._h2o_ari_config()
        url = '%s/ari/asterisk/config/dynamic/res_pjsip/%s/%s' % (url, object_type, self.extension)
        body = None
        if fields_values is not None:
            body = {'fields': [{'attribute': key, 'value': value} for key, value in fields_values.items()]}
        try:
            response = requests.request(method, url, json=body, auth=auth, timeout=ARI_TIMEOUT)
        except requests.RequestException as e:
            raise UserError(self.env._("Asterisk could not be reached: %s", e)) from e
        if method == 'DELETE' and response.status_code == 404:
            return  # already gone
        if not response.ok:
            raise UserError(self.env._("Asterisk refused the %(type)s of extension %(extension)s: %(status)s %(error)s",
                                       type=object_type, extension=self.extension,
                                       status=response.status_code, error=response.text))

    def _h2o_issue_credentials(self):
        """Give the account a new random password on Asterisk and return what the app needs to register."""
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()
        hours = params.get_int('h2o_telephony.sip_credential_hours') or 12
        expires_at = fields.Datetime.now() + timedelta(hours=hours)
        password = secrets.token_urlsafe(24)

        self._h2o_ari_request('PUT', 'auth', {
            'auth_type': 'userpass',
            'username': self.extension,
            'password': password,
        })
        self._h2o_ari_request('PUT', 'aor', {
            'max_contacts': '1',
            'remove_existing': 'yes',
        })
        self._h2o_ari_request('PUT', 'endpoint', {
            'transport': WSS_TRANSPORT,
            'context': DRIVER_CONTEXT,
            'aors': self.extension,
            'auth': self.extension,
            'webrtc': 'yes',
            'ice_support': 'yes',
            'disallow': 'all',
            'allow': 'alaw',
            'callerid': '"%s" <%s>' % (self.user_id.name, self.extension),
        })
        # sudo: drivers read their own account but only the expiry may change, here.
        self.sudo().password_expires_at = expires_at
        return {
            'username': self.extension,
            'password': password,
            'domain': params.get_str('h2o_telephony.sip_domain'),
            'wss_url': params.get_str('h2o_telephony.wss_url'),
            'expires_at': expires_at.isoformat() + 'Z',
            'ice_servers': ICE_SERVERS,
        }

    def _h2o_revoke(self):
        """Remove the password from Asterisk: the app cannot register until it asks for new credentials."""
        for account in self:
            account._h2o_ari_request('DELETE', 'auth')
            account.sudo().password_expires_at = False

    @api.model
    def _cron_h2o_revoke_expired(self):
        accounts = self.with_context(active_test=False).search([('password_expires_at', '<=', fields.Datetime.now())])
        for account in accounts:
            try:
                account._h2o_revoke()
            except UserError as e:
                # Tried again at the next run.
                _logger.warning("SIP credentials of extension %s not revoked: %s", account.extension, e)

    # ------------------------------------------------------------
    # Driver app wake-up
    # ------------------------------------------------------------

    def _h2o_wake(self, call_id, caller):
        """Wake the driver app so it registers and Asterisk can ring it."""
        self.ensure_one()
        partner = self.env['res.partner']._h2o_find_by_phone(caller)
        return self.env['h2o.push.device']._h2o_send(self.user_id, {
            'type': 'incoming_call',
            'call_id': call_id,
            'extension': self.extension,
            'caller': caller or '',
            'caller_name': partner.display_name or '',
            'partner_id': partner.id or '',
        }, priority='high', ttl=30, app='driver')

    def _h2o_cancel(self, call_id):
        """Tell the driver app to stop ringing: the caller hung up or someone else answered."""
        self.ensure_one()
        return self.env['h2o.push.device']._h2o_send(self.user_id, {
            'type': 'call_cancelled',
            'call_id': call_id,
            'extension': self.extension,
        }, priority='high', ttl=30, app='driver')
