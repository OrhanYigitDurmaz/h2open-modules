from datetime import date

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from h2open_mcp.odoo import Odoo, OdooConfig, OdooError
from h2open_mcp.server import clean, normalize_phone, parse_date, phone_pattern


def test_normalize_phone_any_format():
    for number in ("+90 532 111 22 33", "0532 111 2233", "(0532) 111-22-33", "5321112233"):
        assert normalize_phone(number) == "5321112233"
    assert normalize_phone(False) == ""


def test_phone_pattern_allows_separators():
    assert phone_pattern("5321") == "5%3%2%1"


def test_parse_date():
    today = date(2026, 10, 18)
    assert parse_date(None, today) == "2026-10-18"
    assert parse_date(None, today, default_days=1) == "2026-10-19"
    assert parse_date("Tomorrow", today) == "2026-10-19"
    assert parse_date("yesterday", today) == "2026-10-17"
    assert parse_date("2026-11-02", today) == "2026-11-02"
    with pytest.raises(ToolError):
        parse_date("02/11/2026", today)


def test_clean_many2one():
    assert clean({"id": 1, "partner_id": [3, "Ayşe"], "zone_id": False, "name": "x"}, "partner_id", "zone_id") == {
        "id": 1, "partner_id": {"id": 3, "name": "Ayşe"}, "zone_id": None, "name": "x"}


def _odoo(handler):
    return Odoo(OdooConfig("http://odoo.test", "h2open", "secret"), transport=httpx.MockTransport(handler))


def test_call_sends_key_database_and_ids():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = request.read()
        return httpx.Response(200, json=True)

    assert _odoo(handler).call("h2o.trip", "action_start", ids=[7]) is True
    assert seen["url"] == "http://odoo.test/json/2/h2o.trip/action_start"
    assert seen["headers"]["authorization"] == "bearer secret"
    assert seen["headers"]["x-odoo-database"] == "h2open"
    assert seen["body"] == b'{"ids":[7]}'


def test_call_raises_odoo_message():
    def handler(request):
        return httpx.Response(422, json={"name": "odoo.exceptions.UserError", "message": "Trip is closed."})

    with pytest.raises(OdooError, match="Trip is closed."):
        _odoo(handler).call("h2o.trip", "action_close", ids=[1])


def test_call_explains_bad_key():
    def handler(request):
        return httpx.Response(401, json={"name": "werkzeug.exceptions.Unauthorized", "message": "Invalid apikey"})

    with pytest.raises(OdooError, match="H2OPEN_API_KEY"):
        _odoo(handler).call("res.partner", "search_read", domain=[])
