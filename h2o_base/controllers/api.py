"""Shared JSON API for the H2Open mobile apps.

Apps sign in once with ``POST /h2o/api/v1/login`` and get a short-lived
access token (an API key scoped to ``h2o_app``) plus a long-lived refresh
token. Every other app route is declared with :func:`h2o_route`, which
requires the access token as ``Authorization: Bearer <token>``. Before it
expires, or after a 401, the app swaps the refresh token for a new pair with
``POST /h2o/api/v1/token/refresh``; the old pair stops working. Bodies and
responses are plain JSON (Odoo's ``json2`` route type); errors come back as
JSON with an HTTP error status.
"""
import logging

from werkzeug.exceptions import Unauthorized

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools import SQL

from odoo.addons.h2o_base.models.h2o_app_session import H2O_APP_SCOPE

_logger = logging.getLogger(__name__)

API_PREFIX = '/h2o/api/v1'


def h2o_route(path, methods=('POST',), **kwargs):
    """Declare an authenticated H2Open app route (bearer token, JSON in and out)."""
    return http.route(
        path,
        type='json2',
        auth='bearer',
        bearer_scope=H2O_APP_SCOPE,
        methods=list(methods),
        csrf=False,
        save_session=False,
        **kwargs,
    )


class H2oApiController(http.Controller):

    @http.route(f'{API_PREFIX}/login', type='json2', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def h2o_login(self, login=None, password=None, device_name=None, **kw):
        if not login or not password:
            raise Unauthorized("login and password are required")
        credential = {'type': 'password', 'login': login, 'password': password}
        try:
            auth_info = request.env['res.users'].sudo()._login(credential, user_agent_env={'interactive': True})
        except AccessDenied:
            raise Unauthorized("Wrong login or password") from None
        user = request.env['res.users'].sudo().browse(auth_info['uid'])
        if not user._h2o_app_roles():
            raise Unauthorized("This user has no H2Open role")
        tokens = user._h2o_app_login(device_name)
        # 'token' is the old name of access_token, kept until the driver app reads access_token.
        return tokens | {'token': tokens['access_token'], 'user': user._h2o_app_profile()}

    @http.route(f'{API_PREFIX}/token/refresh', type='json2', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def h2o_token_refresh(self, refresh_token=None, **kw):
        tokens = request.env['h2o.app.session'].sudo()._h2o_refresh(refresh_token)
        if not tokens:
            # A response, not an exception: a reused token has just signed the
            # device out, and that must be committed.
            return request.dispatcher.handle_error(Unauthorized("Sign in again"))
        return tokens

    @h2o_route(f'{API_PREFIX}/logout')
    def h2o_logout(self, **kw):
        # Only this device is signed out; other devices stay signed in.
        session = request.env['h2o.app.session']._h2o_current()
        if session:
            session._h2o_revoke('logout')
            return {'ok': True}
        # A key issued before device sessions existed: the bearer check already
        # validated it, so its 8-char index identifies it.
        token = request.httprequest.headers.get('Authorization', '').split(' ', 1)[-1].strip()
        request.env.cr.execute(SQL(
            "DELETE FROM res_users_apikeys WHERE user_id = %s AND scope = %s AND index = %s",
            request.env.uid, H2O_APP_SCOPE, token[:8],
        ))
        request.env.transaction.invalidate_ormcache()
        return {'ok': True}

    @h2o_route(f'{API_PREFIX}/me', methods=('GET', 'POST'))
    def h2o_me(self, **kw):
        return request.env.user._h2o_app_profile()
