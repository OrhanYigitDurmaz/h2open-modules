"""Routes called by Asterisk, and the SIP credentials route of the driver app.

Asterisk authenticates with a shared secret in the ``X-H2O-Secret`` header;
its routes are refused while no secret is configured. Asterisk acts for no
user in particular, so these routes work as superuser once the secret matches.
"""
import hmac

from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from odoo import SUPERUSER_ID, http
from odoo.http import request

from odoo.addons.h2o_base.controllers.api import API_PREFIX, h2o_route
from odoo.addons.h2o_telephony.models.h2o_call import CALL_EVENTS

TELEPHONY_PREFIX = '/h2o/telephony/v1'


def asterisk_route(path, readonly=False):
    # auth='none' routes default to a read-only cursor: say so explicitly, the
    # routes that write must never be replayed (a push is not idempotent).
    return http.route(f'{TELEPHONY_PREFIX}/{path}', type='json2', auth='none', methods=['POST'],
                      csrf=False, save_session=False, readonly=readonly)


class H2oTelephonyController(http.Controller):

    def _h2o_asterisk_env(self):
        """Check the shared secret and return a superuser environment."""
        expected = request.env['ir.config_parameter'].sudo().get_str('h2o_telephony.asterisk_secret')
        given = request.httprequest.headers.get('X-H2O-Secret', '')
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            raise Forbidden("Invalid secret")
        return request.env(user=SUPERUSER_ID, su=True)

    def _h2o_sip_account(self, env, extension):
        if not extension:
            raise BadRequest("extension is required")
        account = env['h2o.sip.account'].search([('extension', '=', str(extension))], limit=1)
        if not account:
            raise NotFound("Unknown extension")
        return account

    @asterisk_route('lookup', readonly=True)
    def h2o_lookup(self, number=None, **kw):
        env = self._h2o_asterisk_env()
        partner = env['res.partner']._h2o_find_by_phone(number)
        return {'name': partner.display_name or '', 'partner_id': partner.id or None}

    @asterisk_route('event')
    def h2o_event(self, uniqueid=None, event=None, caller=None, called=None, direction='inbound',
                  extension=None, **kw):
        env = self._h2o_asterisk_env()
        if not uniqueid or event not in CALL_EVENTS:
            raise BadRequest("uniqueid and event (ring, answer or hangup) are required")
        if direction not in dict(env['h2o.call']._fields['direction'].selection):
            raise BadRequest("direction must be inbound, outbound or internal")
        call = env['h2o.call']._h2o_from_event(
            str(uniqueid), event, caller=caller, called=called, direction=direction,
            extension=extension and str(extension))
        return {'call_id': call.id, 'state': call.state, 'partner_id': call.partner_id.id or None}

    @asterisk_route('wake')
    def h2o_wake(self, extension=None, call_id=None, caller=None, **kw):
        env = self._h2o_asterisk_env()
        return self._h2o_sip_account(env, extension)._h2o_wake(call_id, caller)

    @asterisk_route('cancel')
    def h2o_cancel(self, extension=None, call_id=None, **kw):
        env = self._h2o_asterisk_env()
        return self._h2o_sip_account(env, extension)._h2o_cancel(call_id)

    @h2o_route(f'{API_PREFIX}/sip/credentials')
    def h2o_sip_credentials(self, **kw):
        account = request.env['h2o.sip.account'].search([('user_id', '=', request.env.uid)], limit=1)
        if not account:
            raise NotFound("No SIP account for this user")
        return account._h2o_issue_credentials()
