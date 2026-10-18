import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

H2O_APP_SCOPE = 'h2o_app'

# A refresh token presented again this soon after it was rotated is taken as a
# retry of a request whose answer never reached the phone, not as theft.
REFRESH_RETRY_SECONDS = 60
# How often a used access token moves the session's "last used" time.
LAST_USED_RESOLUTION = timedelta(minutes=5)
# Revoked and expired sessions are kept this long for the device list, then deleted.
KEEP_ENDED_DAYS = 30


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class H2oAppSession(models.Model):
    """One signed-in phone of a mobile app user.

    The phone holds two secrets: a short-lived access token (an ``h2o_app``
    scoped ``res.users.apikeys`` key, sent as bearer on every app route) and a
    long-lived refresh token, swapped for a new pair by
    ``POST /h2o/api/v1/token/refresh``. Every refresh rotates both; Odoo keeps
    only hashes. Presenting a refresh token that was already rotated signs the
    device out, since only a copy of the token can do that.

    Refresh tokens look like ``<ref>.<secret>``: ``ref`` finds the session,
    the SHA-256 of the whole token must match the stored hash.
    """
    _name = 'h2o.app.session'
    _description = 'App Device Session'
    _order = 'last_used desc, id desc'
    _rec_name = 'device_name'

    user_id = fields.Many2one('res.users', string="User", required=True, index=True, ondelete='cascade',
                              readonly=True)
    device_name = fields.Char(string="Device", readonly=True)
    ref = fields.Char(required=True, readonly=True, copy=False, groups='base.group_system')
    refresh_hash = fields.Char(readonly=True, copy=False, groups='base.group_system')
    previous_hash = fields.Char(readonly=True, copy=False, groups='base.group_system')
    rotated_at = fields.Datetime(readonly=True, copy=False)
    api_key_id = fields.Many2one('res.users.apikeys', string="Access Key", ondelete='set null', readonly=True,
                                 copy=False, groups='base.group_system')
    access_expires_at = fields.Datetime(string="Access Expires", readonly=True)
    refresh_expires_at = fields.Datetime(string="Sign-in Expires", readonly=True,
                                         help="The app has to sign in again if it is not used before this time.")
    last_used = fields.Datetime(string="Last Used", readonly=True)
    state = fields.Selection([('active', "Signed in"), ('revoked', "Signed out")], required=True,
                             default='active', readonly=True)
    revoked_at = fields.Datetime(string="Signed Out On", readonly=True)
    revoke_reason = fields.Selection([
        ('logout', "Signed out on the phone"),
        ('manager', "Signed out by a manager"),
        ('reuse', "Old sign-in token reused"),
        ('user', "User deactivated or password changed"),
    ], string="Sign-out Reason", readonly=True)
    is_expired = fields.Boolean(compute='_compute_is_expired', string="Expired")

    _ref_unique = models.Constraint('UNIQUE(ref)', 'Session references must be unique.')

    @api.depends('refresh_expires_at')
    def _compute_is_expired(self):
        now = fields.Datetime.now()
        for session in self:
            session.is_expired = bool(session.refresh_expires_at and session.refresh_expires_at < now)

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------

    @api.model
    def _h2o_start(self, user, device_name=None):
        """Sign ``user`` in on a new device and return the token dict for the app."""
        session = self.sudo().create({
            'user_id': user.id,
            'device_name': device_name or "unknown device",
            'ref': secrets.token_hex(8),
        })
        return session._h2o_issue_tokens()

    def _h2o_issue_tokens(self):
        """Replace the access and refresh tokens of the session and return them."""
        self.ensure_one()
        company = self.user_id.company_id
        now = fields.Datetime.now()
        access_expires = now + timedelta(hours=company.h2o_app_access_hours or 24)
        refresh_expires = now + timedelta(days=company.h2o_app_refresh_days or 90)
        refresh_expires = max(refresh_expires, access_expires)

        self._h2o_delete_access_key()
        name = "H2Open app: %s" % self.device_name
        # sudo: the key may outlive what the user's own groups allow (_check_expiration_date).
        access_token = self.env['res.users.apikeys'].with_user(self.user_id).sudo()._generate(
            H2O_APP_SCOPE, name, access_expires)
        self.env.cr.execute(SQL(
            "SELECT id FROM res_users_apikeys WHERE user_id = %s AND scope = %s AND index = %s ORDER BY id DESC LIMIT 1",
            self.user_id.id, H2O_APP_SCOPE, access_token[:8],
        ))
        key_id = self.env.cr.fetchone()[0]

        refresh_token = "%s.%s" % (self.sudo().ref, secrets.token_urlsafe(32))
        self.sudo().write({
            'previous_hash': self.sudo().refresh_hash,
            'refresh_hash': _hash(refresh_token),
            'rotated_at': now,
            'api_key_id': key_id,
            'access_expires_at': access_expires,
            'refresh_expires_at': refresh_expires,
            'last_used': now,
        })
        return {
            'access_token': access_token,
            'access_expires_at': self._h2o_iso(access_expires),
            'access_expires_in': int((access_expires - now).total_seconds()),
            'refresh_token': refresh_token,
            'refresh_expires_at': self._h2o_iso(refresh_expires),
            'refresh_expires_in': int((refresh_expires - now).total_seconds()),
        }

    @api.model
    def _h2o_refresh(self, refresh_token):
        """Swap a refresh token for a new token pair.

        :return: the token dict, or ``None`` when the token is unknown,
            expired or revoked. Reuse of a rotated token signs the session out
            (the caller must still commit, so return an error response rather
            than raising).
        """
        if not refresh_token or not isinstance(refresh_token, str) or '.' not in refresh_token:
            return None
        ref = refresh_token.split('.', 1)[0]
        # Lock the row: two refreshes with the same token must not both succeed.
        self.env.cr.execute(SQL("SELECT id FROM h2o_app_session WHERE ref = %s FOR UPDATE", ref))
        row = self.env.cr.fetchone()
        if not row:
            return None
        session = self.sudo().browse(row[0])
        session.invalidate_recordset()
        if session.state != 'active' or session.is_expired:
            return None
        if not session.user_id.active or not session.user_id._h2o_app_roles():
            session._h2o_revoke('user')
            return None

        presented = _hash(refresh_token)
        if hmac.compare_digest(presented, session.refresh_hash or ''):
            return session._h2o_issue_tokens()
        if (session.previous_hash and hmac.compare_digest(presented, session.previous_hash)
                and session.rotated_at
                and fields.Datetime.now() - session.rotated_at <= timedelta(seconds=REFRESH_RETRY_SECONDS)):
            # The phone retried a refresh whose answer it never got: give it a
            # fresh pair; the pair it missed stops working.
            session.refresh_hash = session.previous_hash
            tokens = session._h2o_issue_tokens()
            session.previous_hash = False  # one retry only
            return tokens
        _logger.warning("H2Open app session %s of %s: rotated refresh token reused, signing the device out",
                        session.id, session.user_id.login)
        session._h2o_revoke('reuse')
        return None

    @api.model
    def _h2o_current(self):
        """Return the active session whose access token authenticated the
        current request (already validated by the bearer check), or an empty
        recordset."""
        token = request and request.httprequest.headers.get('Authorization', '').split(' ', 1)[-1].strip()
        if not token:
            return self.browse()
        self.env.cr.execute(SQL(
            """SELECT s.id FROM h2o_app_session s JOIN res_users_apikeys k ON k.id = s.api_key_id
               WHERE k.index = %s AND k.user_id = %s AND k.scope = %s AND s.state = 'active'
               ORDER BY s.id DESC LIMIT 1""",
            token[:8], self.env.uid, H2O_APP_SCOPE,
        ))
        row = self.env.cr.fetchone()
        return self.sudo().browse(row[0]) if row else self.browse()

    @api.model
    def _h2o_touch(self, user_id, token):
        """Move ``last_used`` of the session using ``token``, at most every few minutes."""
        self.env.cr.execute(SQL(
            """UPDATE h2o_app_session s SET last_used = now() at time zone 'utc'
               FROM res_users_apikeys k
               WHERE k.id = s.api_key_id AND k.index = %s AND k.user_id = %s AND k.scope = %s
                 AND (s.last_used IS NULL OR s.last_used < (now() at time zone 'utc') - %s)""",
            token[:8], user_id, H2O_APP_SCOPE, LAST_USED_RESOLUTION,
        ))
        if self.env.cr.rowcount:
            self.invalidate_model(['last_used'])

    # ------------------------------------------------------------------
    # Sign out
    # ------------------------------------------------------------------

    def _h2o_delete_access_key(self):
        keys = self.sudo().api_key_id
        if keys:
            self.env.cr.execute(SQL("DELETE FROM res_users_apikeys WHERE id IN %s", tuple(keys.ids)))
            self.sudo().invalidate_recordset(['api_key_id'])
            self.env.transaction.invalidate_ormcache()

    def _h2o_revoke(self, reason):
        """Sign the sessions out: their access and refresh tokens stop working at once."""
        sessions = self.filtered(lambda s: s.state == 'active')
        if not sessions:
            return
        sessions._h2o_delete_access_key()
        sessions.sudo().write({
            'state': 'revoked',
            'revoked_at': fields.Datetime.now(),
            'revoke_reason': reason,
            'refresh_hash': False,
            'previous_hash': False,
        })

    def action_h2o_sign_out(self):
        if not self.env.user.has_group('h2o_base.group_h2o_manager'):
            raise AccessError(self.env._("Only H2Open managers can sign devices out."))
        self.sudo()._h2o_revoke('manager')
        return True

    # ------------------------------------------------------------------

    @api.model
    def _h2o_iso(self, value):
        return value.replace(microsecond=0).isoformat() + 'Z'

    @api.autovacuum
    def _gc_h2o_app_sessions(self):
        limit = fields.Datetime.now() - timedelta(days=KEEP_ENDED_DAYS)
        ended = self.sudo().search(['|',
                                    '&', ('state', '=', 'revoked'), ('revoked_at', '<', limit),
                                    ('refresh_expires_at', '<', limit)])
        ended._h2o_delete_access_key()
        ended.unlink()
