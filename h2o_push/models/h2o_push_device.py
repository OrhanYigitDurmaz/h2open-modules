import base64
import json
import logging
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

FCM_SEND_URL = 'https://fcm.googleapis.com/v1/projects/%s/messages:send'
FCM_SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
TIMEOUT = 10

# OAuth2 access tokens per service account key: {(client_email, private_key_id): (token, expires_at)}.
# Shared by the databases of this process; a token is only reused for the very same key.
_access_tokens = {}


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=')


class H2oPushDevice(models.Model):
    _name = 'h2o.push.device'
    _description = 'Push Device'
    _order = 'last_seen desc, id desc'
    _rec_name = 'device_name'

    user_id = fields.Many2one('res.users', string="User", required=True, index=True, ondelete='cascade')
    token = fields.Char(string="FCM Token", required=True)
    platform = fields.Selection([('android', "Android"), ('ios', "iOS")], required=True, default='android')
    app = fields.Selection([('driver', "Driver app"), ('customer', "Customer app")], required=True, default='driver')
    device_name = fields.Char(string="Device")
    last_seen = fields.Datetime(default=fields.Datetime.now)
    active = fields.Boolean(default=True)

    _token_unique = models.Constraint('UNIQUE(token)', 'This push token is already registered.')

    @api.model
    def _h2o_register(self, token, platform, app, device_name=None):
        """Register the FCM token of the current user's device and return the device.

        A token belongs to one app installation: when it was registered before,
        possibly by another user who signed in on the same phone, it moves to
        the current user.
        """
        # sudo: the token may still be held by another user's device, which the
        # current user can neither see nor take over with their own rights.
        device = self.sudo().with_context(active_test=False).search([('token', '=', token)])
        vals = {
            'user_id': self.env.uid,
            'platform': platform,
            'app': app,
            'device_name': device_name,
            'last_seen': fields.Datetime.now(),
            'active': True,
        }
        if device:
            device.write(vals)
        else:
            device = device.create(vals | {'token': token})
        return device.sudo(False)

    @api.model
    def _h2o_send(self, users, data, notification=None, priority='high', ttl=60, app=None):
        """Push a message to every active device of ``users``.

        :param users: ``res.users`` recordset
        :param dict data: data payload; values are sent as strings
        :param dict notification: optional ``{'title': ..., 'body': ...}`` shown by the phone
        :param str priority: ``high`` (wakes the app at once) or ``normal``
        :param int ttl: seconds FCM keeps the message for an offline device
        :param str app: only devices of this app (``driver`` or ``customer``)
        :return: ``{'sent': int, 'failed': int, 'deactivated': int}``

        Never raises on configuration or network errors: they are logged and
        counted as failures.
        """
        domain = [('user_id', 'in', users.ids)]
        if app:
            domain.append(('app', '=', app))
        # sudo: anyone may trigger a push to another user (a dispatcher to a
        # driver, Asterisk to a driver); only the devices are read and logged.
        devices = self.sudo().search(domain)
        result = {'sent': 0, 'failed': 0, 'deactivated': 0}
        if not devices:
            return result

        data = {str(key): '' if value is None else str(value) for key, value in data.items()}
        try:
            account, project_id = self._h2o_fcm_config()
            access_token = self._h2o_fcm_access_token(account)
        except (UserError, requests.RequestException, ValueError, KeyError) as e:
            _logger.warning("Push notifications not sent: %s", e)
            self.env['h2o.push.log'].sudo().create(
                [device._h2o_log_vals(data, 'failed', str(e)) for device in devices])
            result['failed'] = len(devices)
            return result

        log_vals = []
        for device in devices:
            error, unregistered = device._h2o_fcm_post(project_id, access_token, account, data,
                                                       notification, priority, ttl)
            log_vals.append(device._h2o_log_vals(data, 'failed' if error else 'sent', error))
            if not error:
                result['sent'] += 1
                continue
            result['failed'] += 1
            if unregistered:
                device.active = False
                result['deactivated'] += 1
        self.env['h2o.push.log'].sudo().create(log_vals)
        return result

    def _h2o_fcm_post(self, project_id, access_token, account, data, notification, priority, ttl):
        """Send one FCM message to this device. Return ``(error, unregistered)``."""
        self.ensure_one()
        high = priority == 'high'
        message = {
            'token': self.token,
            'data': data,
            'android': {'priority': 'HIGH' if high else 'NORMAL', 'ttl': '%ss' % ttl},
            'apns': {'headers': {
                # Apple only accepts priority 10 for messages that show something.
                'apns-priority': '10' if high and notification else '5',
                'apns-expiration': str(int(time.time()) + ttl),
            }},
        }
        if notification:
            message['notification'] = notification
        else:
            message['apns']['payload'] = {'aps': {'content-available': 1}}
        try:
            response = requests.post(
                FCM_SEND_URL % project_id,
                json={'message': message},
                headers={'Authorization': 'Bearer %s' % access_token},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            _logger.warning("FCM request failed for device %s: %s", self.id, e)
            return str(e), False
        if response.ok:
            return None, False

        try:
            error = response.json().get('error', {})
        except ValueError:
            error = {}
        codes = {detail.get('errorCode') for detail in error.get('details', [])}
        if response.status_code == 401:
            # The cached access token was revoked or expired early: get a new one next time.
            _access_tokens.pop(self._h2o_token_cache_key(account), None)
        message = error.get('message') or response.text or str(response.status_code)
        _logger.info("FCM refused the message for device %s: %s %s", self.id, response.status_code, message)
        unregistered = 'UNREGISTERED' in codes or response.status_code == 404
        return '%s %s' % (response.status_code, message), unregistered

    def _h2o_log_vals(self, data, state, error=None):
        self.ensure_one()
        return {'user_id': self.user_id.id, 'device_id': self.id, 'data': data, 'state': state, 'error': error}

    @api.model
    def _h2o_fcm_config(self):
        """Return ``(service account dict, project id)`` from the settings."""
        params = self.env['ir.config_parameter'].sudo()
        raw = params.get_str('h2o_push.fcm_service_account')
        if not raw:
            raise UserError(self.env._("The FCM service account is not configured."))
        try:
            account = json.loads(raw)
        except ValueError:
            raise UserError(self.env._("The FCM service account is not valid JSON.")) from None
        if not isinstance(account, dict) or not account.get('client_email') or not account.get('private_key'):
            raise UserError(self.env._("The FCM service account has no client_email or private_key."))
        project_id = params.get_str('h2o_push.fcm_project_id') or account.get('project_id')
        if not project_id:
            raise UserError(self.env._("The FCM project ID is not configured."))
        return account, project_id

    @api.model
    def _h2o_token_cache_key(self, account):
        return account['client_email'], account.get('private_key_id')

    @api.model
    def _h2o_fcm_access_token(self, account):
        """Return an OAuth2 access token for the service account, cached until it expires."""
        key = self._h2o_token_cache_key(account)
        now = int(time.time())
        token, expires_at = _access_tokens.get(key, (None, 0))
        if token and expires_at - 60 > now:
            return token

        header = {'alg': 'RS256', 'typ': 'JWT'}
        if account.get('private_key_id'):
            header['kid'] = account['private_key_id']
        claims = {
            'iss': account['client_email'],
            'scope': FCM_SCOPE,
            'aud': GOOGLE_TOKEN_URL,
            'iat': now,
            'exp': now + 3600,
        }
        signing_input = b'.'.join(_b64url(json.dumps(part).encode()) for part in (header, claims))
        private_key = serialization.load_pem_private_key(account['private_key'].encode(), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        assertion = b'.'.join((signing_input, _b64url(signature))).decode()

        response = requests.post(GOOGLE_TOKEN_URL, data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': assertion,
        }, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        token = payload['access_token']
        _access_tokens[key] = (token, now + int(payload.get('expires_in', 3600)))
        return token
