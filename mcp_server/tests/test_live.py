"""End-to-end run of the tools against a real Odoo with the h2o_* modules and their demo data.

Needs H2OPEN_URL, H2OPEN_DB and H2OPEN_API_KEY (a dispatcher or manager, e.g. admin), and
optionally H2OPEN_TEST_DRIVER_KEY (a driver's key) for the access rights test. It changes
data (orders, trips, deliveries), so point it at a throwaway database.
"""

import json
import os
from datetime import date, timedelta

import pytest
from mcp import Client

from h2open_mcp.odoo import Odoo, OdooConfig
from h2open_mcp.server import build_server

pytestmark = pytest.mark.skipif(not os.environ.get("H2OPEN_API_KEY"), reason="no live Odoo configured")


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


def _server(api_key=None):
    config = OdooConfig.from_env()
    if api_key:
        config.api_key = api_key
    return build_server(Odoo(config))


async def call(client, name, **arguments):
    result = await client.call_tool(name, arguments)
    assert not result.is_error, f"{name} failed: {result.content[0].text}"
    return result.structured_content


async def call_error(client, name, **arguments):
    result = await client.call_tool(name, arguments)
    assert result.is_error, f"{name} should have failed: {result.structured_content}"
    return result.content[0].text


def next_weekday(days_ahead=7):
    """A Monday to Friday date, a week ahead so it does not clash with demo data."""
    day = date.today() + timedelta(days=days_ahead)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


@pytest.mark.anyio
async def test_dispatcher_day():
    async with Client(_server()) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        assert {"plan_trips", "deliver_stop", "day_overview"} <= tools

        # Find the demo customer by phone, written differently than stored.
        found = (await call(client, "find_customers", query="0532 111 2233"))["customers"]
        assert [c["name"] for c in found] == ["Ayşe Yılmaz"]
        customer = found[0]
        by_name = (await call(client, "find_customers", query="ayşe"))["customers"]
        assert customer["id"] in [c["id"] for c in by_name]

        overview = await call(client, "customer_overview", customer_id=customer["id"])
        assert overview["delivery_days"]["days"]
        assert overview["bottles_by_type"][0]["held"] == customer["h2o_bottle_balance"]

        products = (await call(client, "list_products"))["products"]
        water = next(p for p in products if p["h2o_product_kind"] == "water_returnable")
        routes = (await call(client, "list_routes"))["routes"]
        assert any(z["name"] == overview["h2o_zone_id"]["name"] for r in routes for z in r["zones"])

        # Take a phone order for the planning day.
        day = next_weekday()
        order = await call(client, "create_phone_order", customer_id=customer["id"],
                           lines=[{"product_id": water["id"], "qty": 3}], delivery_date=day,
                           time_window="morning", empties_expected=2)
        assert order["state"] == "sale"
        assert order["h2o_delivery_state"] == "to_plan"
        assert order["h2o_delivery_date"] == day
        # 3 bottles out, 2 back: one deposit charged
        assert sum(line["product_uom_qty"] for line in order["lines"] if line["product_id"]["id"] != water["id"]) == 1

        waiting = await call(client, "list_delivery_orders", delivery_state="to_plan", date_to=day)
        assert order["id"] in [o["id"] for o in waiting["orders"]]

        # Plan the day and drive the trip that has our order.
        planned = await call(client, "plan_trips", date=day)
        assert planned["trips"]
        for planned_trip in planned["trips"]:
            trip = await call(client, "get_trip", trip_id=planned_trip["id"])
            if order["id"] in [s["order_id"]["id"] for s in trip["stops"]]:
                break
        else:
            pytest.fail("the new order was not planned")
        assert trip["state"] == "planned"
        stops = trip["stops"]
        ours = next(s for s in stops if s["order_id"]["id"] == order["id"])
        assert ours["address"]["phone"]
        assert ours["lines"][0]["qty_planned"]

        error = await call_error(client, "deliver_stop", stop_id=ours["id"])
        assert "Start trip" in error

        started = await call(client, "trip_action", trip_id=trip["id"], action="start")
        assert started["state"] == "on_road"

        delivered = await call(client, "deliver_stop", stop_id=ours["id"], empties_collected=2,
                               payment_method="cash")
        assert delivered["state"] == "delivered"
        assert delivered["payment_amount"] == pytest.approx(delivered["amount_due"])
        others = [s for s in stops if s["id"] != ours["id"]]
        if others:
            failed = await call(client, "fail_stop", stop_id=others[0]["id"], reason="not_home", note="No answer")
            assert failed["state"] == "failed"
        for stop in others[1:]:
            assert (await call(client, "skip_stop", stop_id=stop["id"]))["state"] == "skipped"

        closed = await call(client, "trip_action", trip_id=trip["id"], action="close")
        assert closed["state"] == "closed"
        error = await call_error(client, "trip_action", trip_id=trip["id"], action="close")
        assert trip["name"] in error

        after = await call(client, "customer_overview", customer_id=customer["id"])
        assert after["h2o_bottle_balance"] == customer["h2o_bottle_balance"] + 1
        assert after["bottle_ledger"][0]["qty_out"] == 3

        overview = await call(client, "day_overview", date=day)
        assert overview["totals"]["delivered_count"] >= 1
        if others:
            assert overview["failed_or_skipped_stops"][0]["failure_reason"] == "not_home"

        # Count the driver's cash.
        handovers = (await call(client, "list_cash_handovers"))["handovers"]
        handover = next(h for h in handovers if h["trip_id"]["id"] == trip["id"])
        approved = await call(client, "approve_cash_handover", handover_id=handover["id"],
                              counted=handover["expected"] - 5, note="5 TL short")
        assert approved["state"] == "approved"
        assert approved["difference"] == -5

        report = await call(client, "delivery_report", date_from=day, date_to=day, group_by="route")
        row = next(r for r in report["rows"] if r["route"]["name"] == trip["route_id"]["name"])
        assert row["delivered_count"] >= 1
        assert row["bottle_qty"] >= 3

        outstanding = await call(client, "bottles_outstanding")
        assert outstanding["bottles_held"] >= after["h2o_bottle_balance"]

        statements = await call(client, "create_monthly_statements", month=day[:7])
        assert statements["month"] == day[:7]


@pytest.mark.anyio
async def test_subscription_actions():
    async with Client(_server()) as client:
        customers = (await call(client, "find_customers", query="a", limit=50))["customers"]
        subscriptions = []
        for customer in customers:
            overview = await call(client, "customer_overview", customer_id=customer["id"])
            subscriptions += [s for s in overview["subscriptions"] if s["state"] == "active"]
        if not subscriptions:
            pytest.skip("no active subscription in the demo data")
        paused = await call(client, "change_subscription", subscription_id=subscriptions[0]["id"], action="pause")
        assert paused["state"] == "paused"
        resumed = await call(client, "change_subscription", subscription_id=subscriptions[0]["id"], action="resume")
        assert resumed["state"] == "active"


@pytest.mark.anyio
async def test_driver_cannot_plan():
    driver_key = os.environ.get("H2OPEN_TEST_DRIVER_KEY")
    if not driver_key:
        pytest.skip("H2OPEN_TEST_DRIVER_KEY not set")
    async with Client(_server(driver_key)) as client:
        error = await call_error(client, "plan_trips", date=next_weekday(14))
        assert "access" in error.lower() or "not allowed" in error.lower(), error
        result = await client.call_tool("list_cash_handovers", {})
        assert result.is_error or not result.structured_content["handovers"], json.dumps(result.structured_content)


@pytest.mark.anyio
async def test_plan_day_without_routes():
    sunday = date.today() + timedelta(days=6 - date.today().weekday() + 7)
    async with Client(_server()) as client:
        error = await call_error(client, "plan_trips", date=sunday.isoformat())
        assert "No route runs" in error
