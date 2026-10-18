"""MCP tools for H2Open dispatchers and managers.

Every tool goes through the h2o_* modules' own methods and wizards (plan trips,
phone order, deliver a stop, approve a cash handover, ...) over Odoo's JSON-2
API, so Odoo's business rules and the signed-in user's access rights apply.
There is deliberately no generic "write any field" tool.
"""

import functools
import re
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from .odoo import Odoo, OdooError

INSTRUCTIONS = """\
H2Open is the Odoo ERP of a water delivery business in Türkiye: returnable 19 L
bottles (damacana) with a deposit, plus non-returnable packaged water.

How the data fits together:
- Customers (res.partner) have a zone, a customer type (home, office, reseller),
  a payment mode (cash, card, or account = invoiced monthly) and a bottle
  balance: returnable bottles they hold. Empties are the bottles they hand back.
- Delivery orders are confirmed sale orders with a delivery date and a delivery
  state: to_plan, planned, delivered, failed, cancelled.
- Every day, routes (a set of zones served by one vehicle and driver) get a trip.
  Planning a day adds a stop to the trip for every to_plan order of its zones.
  A trip goes planned -> loaded -> on_road -> closed. Stops are delivered,
  failed (the order goes back to to_plan) or skipped.
- Closing a trip creates a cash handover that an accountant or manager counts
  and approves.

Dates are YYYY-MM-DD and default to today in the company's time zone.
Tools marked as changing data act on the live system at once: confirm with the
user before calling them unless they clearly asked for that action.
"""

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

PHONE_DIGITS = 10  # Turkish national number without the leading 0 / +90

TRIP_STATES = Literal["planned", "loaded", "on_road", "closed", "cancelled"]
DELIVERY_STATES = Literal["to_plan", "planned", "delivered", "failed", "cancelled"]
FAILURE_REASONS = Literal["not_home", "refused", "no_access", "no_payment", "other"]
PAYMENT_METHODS = Literal["cash", "card", "account", "none"]
TIME_WINDOWS = Literal["any", "morning", "afternoon", "evening"]
CUSTOMER_TYPES = Literal["home", "office", "reseller"]

REPORT_GROUPS = {
    "day": "date:day",
    "week": "date:week",
    "month": "date:month",
    "route": "route_id",
    "driver": "driver_id",
    "vehicle": "vehicle_id",
    "zone": "zone_id",
    "customer": "partner_id",
    "customer_type": "customer_type",
    "state": "state",
    "failure_reason": "failure_reason",
    "payment_method": "payment_method",
}
REPORT_AGGREGATES = [
    "stop_count:sum", "delivered_count:sum", "success_rate:avg", "bottle_qty:sum",
    "packaged_qty:sum", "empties_collected:sum", "payment_amount:sum",
]

PARTNER_FIELDS = [
    "name", "phone", "email", "street", "street2", "city", "parent_id", "commercial_partner_id",
    "h2o_customer_type", "h2o_zone_id", "h2o_payment_mode", "h2o_bottle_balance", "h2o_deposit_balance",
]
ORDER_FIELDS = [
    "name", "state", "partner_id", "partner_shipping_id", "h2o_zone_id", "h2o_delivery_date",
    "h2o_time_window", "h2o_delivery_state", "h2o_channel", "h2o_empties_expected", "amount_total",
    "h2o_trip_id", "date_order",
]
TRIP_FIELDS = [
    "name", "date", "state", "route_id", "driver_id", "vehicle_id", "stop_count", "pending_count",
    "delivered_count", "failed_count", "planned_bottle_qty", "load_qty", "returned_full_qty",
    "returned_empty_qty", "cash_expected", "cash_handed_in", "last_position_at", "note",
]
STOP_FIELDS = [
    "sequence", "trip_id", "partner_id", "commercial_partner_id", "order_id", "zone_id", "state",
    "time_window", "line_ids", "empties_expected", "empties_collected", "payment_method", "payment_amount", "amount_due",
    "failure_reason", "failure_note", "done_at", "note",
]
HANDOVER_FIELDS = [
    "name", "trip_id", "driver_id", "date", "expected", "counted", "difference", "state", "approved_by", "note",
]


class OrderLine(BaseModel):
    product_id: int = Field(description="Product id, see list_products")
    qty: float = Field(gt=0, description="Quantity in the product's sales unit")


class DeliveredLine(BaseModel):
    product_id: int = Field(description="Product id of a line on the stop")
    qty_delivered: float = Field(ge=0)


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

def normalize_phone(number):
    """The last 10 digits of a Turkish phone number written in any format."""
    return re.sub(r"\D", "", number or "")[-PHONE_DIGITS:]


def phone_pattern(digits):
    """An ilike pattern matching ``digits`` with any separators in between."""
    return "%".join(digits)


def parse_date(value, today, default_days=0):
    """``value`` as an ISO date string: YYYY-MM-DD, today, tomorrow, yesterday or empty (default)."""
    if value is None or value == "":
        return (today + timedelta(days=default_days)).isoformat()
    shortcuts = {"today": 0, "tomorrow": 1, "yesterday": -1}
    if value.lower() in shortcuts:
        return (today + timedelta(days=shortcuts[value.lower()])).isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ToolError(f"Use dates as YYYY-MM-DD, not {value!r}.") from exc


def m2o(value):
    """Odoo's ``[id, name]`` many2one value as a dict, ``None`` when empty."""
    if not value:
        return None
    return {"id": value[0], "name": value[1]}


def clean(record, *m2o_fields):
    """``record`` with its many2one ``[id, name]`` pairs turned into dicts."""
    return {key: m2o(value) if key in m2o_fields else value for key, value in record.items()}


def odoo_errors(func):
    """Report Odoo's own error message (access refused, wrong state...) to the model."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except OdooError as exc:
            raise ToolError(str(exc)) from exc
    return wrapper


# ----------------------------------------------------------------------
# Server
# ----------------------------------------------------------------------

def build_server(odoo: Odoo) -> MCPServer:
    server = MCPServer(name="h2open", instructions=INSTRUCTIONS)
    tz = ZoneInfo(odoo.config.timezone)

    def today():
        return datetime.now(tz).date()

    def tool(annotations, title):
        def decorator(func):
            return server.tool(annotations=annotations, title=title)(odoo_errors(func))
        return decorator

    def names(model, ids):
        return [r["display_name"] for r in odoo.read(model, ids, ["display_name"])]

    def read_trips(domain, order="date desc, route_id, id"):
        trips = odoo.search_read("h2o.trip", domain, TRIP_FIELDS, order=order)
        return [clean(t, "route_id", "driver_id", "vehicle_id") for t in trips]

    def read_stops(domain):
        stops = odoo.search_read("h2o.stop", domain, STOP_FIELDS, order="trip_id, sequence, id")
        line_ids = [line_id for stop in stops for line_id in stop["line_ids"]]
        lines = {
            line["id"]: {
                "product": m2o(line["product_id"]),
                "qty_planned": line["qty_planned"],
                "qty_delivered": line["qty_delivered"],
            }
            for line in odoo.read("h2o.stop.line", line_ids, ["product_id", "qty_planned", "qty_delivered"])
        }
        partners = {
            p["id"]: p for p in odoo.read(
                "res.partner", list({s["partner_id"][0] for s in stops if s["partner_id"]}),
                ["phone", "street", "street2", "city", "h2o_delivery_notes", "h2o_floor", "h2o_has_elevator"],
            )
        }
        result = []
        for stop in stops:
            item = clean(stop, "trip_id", "partner_id", "commercial_partner_id", "order_id", "zone_id")
            item["lines"] = [lines[line_id] for line_id in item.pop("line_ids") if line_id in lines]
            address = partners.get(stop["partner_id"][0]) if stop["partner_id"] else None
            if address:
                item["address"] = clean({k: v for k, v in address.items() if k != "id"})
            result.append(item)
        return result

    def read_orders(domain, limit=None):
        orders = odoo.search_read("sale.order", domain, ORDER_FIELDS, order="h2o_delivery_date, id", limit=limit)
        return [clean(o, "partner_id", "partner_shipping_id", "h2o_zone_id", "h2o_trip_id") for o in orders]

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    @tool(READ, "Find customers")
    def find_customers(
        query: Annotated[str, Field(description="Name, phone number (any format), email or street")],
        limit: int = 10,
    ) -> dict[str, Any]:
        """Find water customers (and their delivery addresses) by name, phone, email or street.

        Returns id, contact details, zone, customer type, payment mode and bottle/deposit balance.
        """
        water = ["|", ("h2o_customer_type", "!=", False), ("parent_id.h2o_customer_type", "!=", False)]
        digits = normalize_phone(query)
        if len(digits) >= 7 and len(digits) >= len(query.replace(" ", "")) * 0.6:
            partners = odoo.search_read(
                "res.partner", water + [("phone", "ilike", phone_pattern(digits))], PARTNER_FIELDS, limit=limit * 5)
            partners = [p for p in partners if normalize_phone(p["phone"]).endswith(digits)][:limit]
        else:
            text = ["|", "|", "|", ("name", "ilike", query), ("email", "ilike", query),
                    ("street", "ilike", query), ("ref", "=ilike", query)]
            partners = odoo.search_read("res.partner", water + text, PARTNER_FIELDS, order="name", limit=limit)
        return {"customers": [
            clean(p, "parent_id", "commercial_partner_id", "h2o_zone_id") for p in partners
        ]}

    @tool(READ, "Customer overview")
    def customer_overview(customer_id: int) -> dict[str, Any]:
        """Everything a dispatcher needs about one customer: contact and delivery details,
        delivery days, bottles held per bottle type, deposit balance, recent and open delivery
        orders, subscriptions, the last bottle ledger entries and unpaid invoices."""
        fields = PARTNER_FIELDS + [
            "h2o_weekday_ids", "h2o_delivery_notes", "h2o_floor", "h2o_has_elevator", "child_ids",
        ]
        found = odoo.read("res.partner", [customer_id], fields)
        if not found:
            raise ToolError(f"No customer with id {customer_id}.")
        partner = found[0]
        commercial_id = partner["commercial_partner_id"][0]
        result = clean(partner, "parent_id", "commercial_partner_id", "h2o_zone_id")
        result.pop("h2o_weekday_ids")
        result["delivery_addresses"] = [
            clean(a, "h2o_zone_id") for a in odoo.read(
                "res.partner", partner["child_ids"], ["name", "type", "street", "street2", "city", "h2o_zone_id"])
        ]
        result.pop("child_ids")

        weekday_ids = partner["h2o_weekday_ids"]
        source = "customer"
        if not weekday_ids and partner["h2o_zone_id"]:
            weekday_ids = odoo.read("h2o.zone", [partner["h2o_zone_id"][0]], ["weekday_ids"])[0]["weekday_ids"]
            source = "zone"
        result["delivery_days"] = {"days": names("h2o.weekday", weekday_ids), "from": source}

        result["bottles_by_type"] = [
            {"bottle": m2o(b["product_id"]), "held": b["qty"], "given": b["qty_out"], "returned": b["qty_in"],
             "deposit": b["deposit_amount"], "last_move": b["last_date"] or None}
            for b in odoo.search_read(
                "h2o.container.balance", [("partner_id", "=", commercial_id)],
                ["product_id", "qty", "qty_out", "qty_in", "deposit_amount", "last_date"])
        ]
        customer = [("partner_id", "child_of", commercial_id)]
        result["open_orders"] = read_orders(
            customer + [("h2o_is_delivery", "=", True), ("state", "=", "sale"),
                        ("h2o_delivery_state", "in", ["to_plan", "planned"])])
        result["recent_deliveries"] = [
            clean(o, "partner_shipping_id") for o in odoo.search_read(
                "sale.order", customer + [("h2o_delivery_state", "in", ["delivered", "failed"])],
                ["name", "h2o_delivery_date", "h2o_delivery_state", "amount_total", "partner_shipping_id"],
                order="h2o_delivery_date desc, id desc", limit=5)
        ]
        result["subscriptions"] = [
            clean(s, "weekday_id", "address_id") for s in odoo.search_read(
                "h2o.subscription", customer + [("state", "!=", "closed")],
                ["name", "state", "frequency", "weekday_id", "next_date", "time_window", "address_id"])
        ]
        result["bottle_ledger"] = [
            clean(m, "product_id") for m in odoo.search_read(
                "h2o.container.move", customer + [("state", "=", "done")],
                ["name", "date", "product_id", "qty_out", "qty_in", "deposit_amount", "source", "origin"],
                order="date desc, id desc", limit=10)
        ]
        try:
            result["unpaid_invoices"] = odoo.search_read(
                "account.move",
                customer + [("move_type", "=", "out_invoice"), ("state", "=", "posted"),
                            ("payment_state", "in", ["not_paid", "partial"])],
                ["name", "invoice_date", "invoice_date_due", "amount_total", "amount_residual"],
                order="invoice_date")
        except OdooError:
            result["unpaid_invoices"] = "not visible to this user"
        return result

    # ------------------------------------------------------------------
    # Orders and planning
    # ------------------------------------------------------------------

    @tool(READ, "List products")
    def list_products() -> dict[str, Any]:
        """Water and bottle products that can be ordered, with their list price and unit."""
        products = odoo.search_read(
            "product.product",
            [("sale_ok", "=", True), ("h2o_product_kind", "in", ["water_returnable", "water_packaged", "container"])],
            ["display_name", "h2o_product_kind", "h2o_volume", "lst_price", "uom_id"], order="h2o_product_kind, name")
        return {"products": [clean(p, "uom_id") for p in products]}

    @tool(READ, "List routes")
    def list_routes() -> dict[str, Any]:
        """Delivery routes with their zones, delivery days, default driver and vehicle."""
        routes = odoo.search_read(
            "h2o.route", [], ["name", "code", "zone_ids", "weekday_ids", "driver_id", "vehicle_id"], order="sequence, name")
        result = []
        for route in routes:
            item = clean(route, "driver_id", "vehicle_id")
            item["zones"] = [{"id": z["id"], "name": z["display_name"]}
                             for z in odoo.read("h2o.zone", item.pop("zone_ids"), ["display_name"])]
            item["days"] = names("h2o.weekday", item.pop("weekday_ids"))
            result.append(item)
        return {"routes": result}

    @tool(READ, "List delivery orders")
    def list_delivery_orders(
        date_from: Annotated[str | None, Field(description="First delivery date (YYYY-MM-DD)")] = None,
        date_to: Annotated[str | None, Field(description="Last delivery date (YYYY-MM-DD)")] = None,
        delivery_state: DELIVERY_STATES | None = None,
        zone_id: int | None = None,
        customer_id: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Confirmed delivery orders, oldest delivery date first. With no filter: every order
        still to plan or planned. Use delivery_state='to_plan' and date_to=<day> to see what
        planning that day would pick up."""
        domain = [("h2o_is_delivery", "=", True), ("state", "=", "sale")]
        if delivery_state:
            domain.append(("h2o_delivery_state", "=", delivery_state))
        elif not (date_from or date_to or customer_id):
            domain.append(("h2o_delivery_state", "in", ["to_plan", "planned"]))
        if date_from:
            domain.append(("h2o_delivery_date", ">=", parse_date(date_from, today())))
        if date_to:
            domain.append(("h2o_delivery_date", "<=", parse_date(date_to, today())))
        if zone_id:
            domain.append(("h2o_zone_id", "=", zone_id))
        if customer_id:
            domain.append(("partner_id", "child_of", customer_id))
        total = odoo.search_count("sale.order", domain)
        return {"total": total, "orders": read_orders(domain, limit=limit)}

    @tool(WRITE, "Create a phone order")
    def create_phone_order(
        customer_id: int,
        lines: Annotated[
            list[OrderLine] | None,
            Field(description="Products to deliver. Empty: repeat the water of the customer's last order."),
        ] = None,
        delivery_address_id: Annotated[int | None, Field(description="Default: the customer's delivery address")] = None,
        delivery_date: Annotated[str | None, Field(description="Default: the customer's next delivery day")] = None,
        time_window: TIME_WINDOWS | None = None,
        empties_expected: Annotated[
            int | None,
            Field(ge=0, description="Empty bottles the customer will hand back. Default: bottles ordered, "
                                    "up to the bottles they hold."),
        ] = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Create and confirm a delivery order, like the New phone order screen. Changes data.

        Deposits for extra bottles are added automatically. The order is then waiting to be planned."""
        vals: dict[str, Any] = {"partner_id": customer_id}
        if lines:
            vals["line_ids"] = [[0, 0, {"product_id": line.product_id, "qty": line.qty}] for line in lines]
        if delivery_address_id:
            vals["partner_shipping_id"] = delivery_address_id
        if delivery_date:
            vals["delivery_date"] = parse_date(delivery_date, today())
        if time_window:
            vals["time_window"] = time_window
        if empties_expected is not None:
            vals["empties_expected"] = empties_expected
        if note:
            vals["note"] = note
        wizard_ids = odoo.call("h2o.quick.order", "create", vals_list=[vals])
        action = odoo.call("h2o.quick.order", "action_create_order", ids=wizard_ids)
        order = read_orders([("id", "=", action["res_id"])])[0]
        order["lines"] = [
            clean(line, "product_id") for line in odoo.search_read(
                "sale.order.line", [("order_id", "=", order["id"]), ("display_type", "=", False)],
                ["product_id", "product_uom_qty", "price_unit", "price_subtotal"])
        ]
        return order

    @tool(WRITE, "Plan trips")
    def plan_trips(
        date: Annotated[str | None, Field(description="Day to plan (YYYY-MM-DD). Default: tomorrow")] = None,
        route_ids: Annotated[list[int] | None, Field(description="Default: every route running that day")] = None,
    ) -> dict[str, Any]:
        """Plan a delivery day, like the Plan Trips button. Changes data.

        For each route running that day, creates (or reuses) its planned trip and adds a stop for
        every confirmed order still to plan in the route's zones, with a delivery date up to that day."""
        vals: dict[str, Any] = {"date": parse_date(date, today(), default_days=1)}
        if route_ids:
            vals["route_ids"] = [[6, 0, route_ids]]
        wizard_ids = odoo.call("h2o.trip.plan", "create", vals_list=[vals])
        if not odoo.read("h2o.trip.plan", wizard_ids, ["route_ids"])[0]["route_ids"]:
            raise ToolError(f"No route runs on {vals['date']}. Pass route_ids to plan routes on that day anyway.")
        action = odoo.call("h2o.trip.plan", "action_plan", ids=wizard_ids)
        trip_ids = [action["res_id"]] if action.get("res_id") else action["domain"][0][2]
        return {"date": vals["date"], "trips": read_trips([("id", "in", trip_ids)])}

    # ------------------------------------------------------------------
    # Trips and stops
    # ------------------------------------------------------------------

    @tool(READ, "List trips")
    def list_trips(
        date: Annotated[str | None, Field(description="YYYY-MM-DD, today, tomorrow. Default: today")] = None,
        state: TRIP_STATES | None = None,
    ) -> dict[str, Any]:
        """The trips of one day with their driver, vehicle, stop counts, bottles and cash."""
        domain = [("date", "=", parse_date(date, today()))]
        if state:
            domain.append(("state", "=", state))
        return {"trips": read_trips(domain)}

    @tool(READ, "Trip details")
    def get_trip(trip_id: int) -> dict[str, Any]:
        """One trip with its ordered stops: address, phone, delivery notes, products, empties,
        payment, amount due and outcome."""
        trips = read_trips([("id", "=", trip_id)])
        if not trips:
            raise ToolError(f"No trip with id {trip_id}.")
        trip = trips[0]
        trip["stops"] = read_stops([("trip_id", "=", trip_id)])
        return trip

    @tool(WRITE, "Move a trip forward")
    def trip_action(
        trip_id: int,
        action: Annotated[
            Literal["load", "start", "close", "cancel", "reset_planned"],
            Field(description="load: vehicle loaded at the depot; start: driver left; close: driver is back "
                              "(every stop must be done); cancel: no delivery happened, orders go back to "
                              "planning; reset_planned: plan a cancelled trip again"),
        ],
    ) -> dict[str, Any]:
        """Load, start, close, cancel or re-plan a trip, like the buttons on the trip. Changes data.

        Loading and closing also move the stock; closing creates the driver's cash handover."""
        odoo.call("h2o.trip", f"action_{action}", ids=[trip_id])
        return read_trips([("id", "=", trip_id)])[0]

    @tool(WRITE, "Record a delivery")
    def deliver_stop(
        stop_id: int,
        lines: Annotated[
            list[DeliveredLine] | None,
            Field(description="Only products not delivered as planned. Default: everything as planned"),
        ] = None,
        empties_collected: Annotated[int | None, Field(ge=0, description="Default: empties expected")] = None,
        payment_method: PAYMENT_METHODS | None = None,
        payment_amount: Annotated[
            float | None, Field(ge=0, description="Default: the amount due for cash and card")] = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Mark a stop delivered, e.g. when a driver phones it in. Changes data.

        The trip must be on the road. Updates the order, the bottle ledger and, for cash and
        card customers, invoices the delivery and registers the payment."""
        vals: dict[str, Any] = {}
        if lines:
            vals["lines"] = [line.model_dump() for line in lines]
        if empties_collected is not None:
            vals["empties_collected"] = empties_collected
        if payment_method:
            vals["payment_method"] = payment_method
        if payment_amount is not None:
            vals["payment_amount"] = payment_amount
        if note:
            vals["note"] = note
        odoo.call("h2o.stop", "action_deliver", ids=[stop_id], vals=vals)
        return read_stops([("id", "=", stop_id)])[0]

    @tool(WRITE, "Record a failed delivery")
    def fail_stop(stop_id: int, reason: FAILURE_REASONS, note: str | None = None) -> dict[str, Any]:
        """Mark a stop failed. The order goes back to planning. Changes data."""
        odoo.call("h2o.stop", "action_fail", ids=[stop_id], reason=reason, note=note)
        return read_stops([("id", "=", stop_id)])[0]

    @tool(WRITE, "Skip a stop")
    def skip_stop(stop_id: int) -> dict[str, Any]:
        """Skip a stop the driver could not get to. The order goes back to planning. Changes data."""
        odoo.call("h2o.stop", "action_skip", ids=[stop_id])
        return read_stops([("id", "=", stop_id)])[0]

    @tool(READ, "Day overview")
    def day_overview(
        date: Annotated[str | None, Field(description="YYYY-MM-DD, today, tomorrow. Default: today")] = None,
    ) -> dict[str, Any]:
        """A dispatcher's summary of one day: trips and their progress, totals, failed or skipped
        stops, orders still waiting to be planned for that day or earlier, and cash to count."""
        day = parse_date(date, today())
        trips = read_trips([("date", "=", day)])
        live = [t for t in trips if t["state"] != "cancelled"]
        totals = {key: sum(t[key] or 0 for t in live) for key in (
            "stop_count", "pending_count", "delivered_count", "failed_count", "planned_bottle_qty",
            "cash_expected", "cash_handed_in")}
        problems = read_stops([("trip_id.date", "=", day), ("state", "in", ["failed", "skipped"])])
        waiting_domain = [("h2o_is_delivery", "=", True), ("state", "=", "sale"),
                          ("h2o_delivery_state", "=", "to_plan"), ("h2o_delivery_date", "<=", day)]
        try:
            handovers = odoo.search_read(
                "h2o.cash.handover", [("trip_id.date", "=", day)], HANDOVER_FIELDS, order="id")
            handovers = [clean(h, "trip_id", "driver_id", "approved_by") for h in handovers]
        except OdooError:
            handovers = "not visible to this user"
        return {
            "date": day,
            "trips": trips,
            "totals": totals,
            "failed_or_skipped_stops": [
                {k: s[k] for k in ("id", "trip_id", "partner_id", "order_id", "state", "failure_reason",
                                   "failure_note")} for s in problems],
            "orders_waiting_to_plan": {
                "count": odoo.search_count("sale.order", waiting_domain),
                "orders": read_orders(waiting_domain, limit=20),
            },
            "cash_handovers": handovers,
        }

    # ------------------------------------------------------------------
    # Bottles, cash and reports
    # ------------------------------------------------------------------

    @tool(READ, "Bottles outstanding")
    def bottles_outstanding(
        zone_id: int | None = None,
        customer_type: CUSTOMER_TYPES | None = None,
        min_bottles: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Customers holding returnable bottles, most bottles first, with the total held
        and the deposit collected for them."""
        domain = [("qty", ">=", min_bottles)]
        if zone_id:
            domain.append(("zone_id", "=", zone_id))
        if customer_type:
            domain.append(("customer_type", "=", customer_type))
        rows = odoo.search_read(
            "h2o.container.balance", domain,
            ["partner_id", "product_id", "qty", "deposit_amount", "zone_id", "customer_type", "last_date"],
            order="qty desc")
        return {
            "customers_holding": len({r["partner_id"][0] for r in rows}),
            "bottles_held": sum(r["qty"] for r in rows),
            "deposit_held": sum(r["deposit_amount"] for r in rows),
            "top": [clean(r, "partner_id", "product_id", "zone_id") for r in rows[:limit]],
        }

    @tool(READ, "Delivery report")
    def delivery_report(
        date_from: Annotated[str | None, Field(description="Default: 30 days ago")] = None,
        date_to: Annotated[str | None, Field(description="Default: today")] = None,
        group_by: Literal[tuple(REPORT_GROUPS)] = "day",
        route_id: int | None = None,
        driver_id: int | None = None,
    ) -> dict[str, Any]:
        """Delivery performance from the Reporting app: stops, delivered stops, success rate
        (% of finished stops delivered), bottles and packaged units delivered, empties collected
        and money collected, grouped by day, route, driver, zone, customer and more."""
        domain = [
            ("date", ">=", parse_date(date_from, today(), default_days=-30)),
            ("date", "<=", parse_date(date_to, today())),
        ]
        if route_id:
            domain.append(("route_id", "=", route_id))
        if driver_id:
            domain.append(("driver_id", "=", driver_id))
        groupby = REPORT_GROUPS[group_by]
        groups = odoo.call("h2o.report.delivery", "formatted_read_group",
                           domain=domain, groupby=[groupby], aggregates=REPORT_AGGREGATES, order=groupby)
        rows = []
        for group in groups:
            key = group[groupby]
            row = {group_by: m2o(key) if isinstance(key, list) else (key or None)}
            for aggregate in REPORT_AGGREGATES:
                value = group.get(aggregate)
                row[aggregate.split(":")[0]] = round(value, 1) if isinstance(value, float) else value
            rows.append(row)
        return {"from": domain[0][2], "to": domain[1][2], "rows": rows}

    @tool(READ, "List cash handovers")
    def list_cash_handovers(
        state: Literal["draft", "approved"] | None = "draft",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Drivers' cash handovers per closed trip: expected, counted and difference.
        Default: the ones still to count (draft)."""
        domain = []
        if state:
            domain.append(("state", "=", state))
        if date_from:
            domain.append(("date", ">=", parse_date(date_from, today())))
        if date_to:
            domain.append(("date", "<=", parse_date(date_to, today())))
        handovers = odoo.search_read("h2o.cash.handover", domain, HANDOVER_FIELDS, order="date desc, id desc")
        return {"handovers": [clean(h, "trip_id", "driver_id", "approved_by") for h in handovers]}

    @tool(WRITE, "Approve a cash handover")
    def approve_cash_handover(
        handover_id: int,
        counted: Annotated[float, Field(ge=0, description="Cash actually counted from the driver")],
        note: str | None = None,
    ) -> dict[str, Any]:
        """Record the cash counted for a driver's handover and approve it. Changes data."""
        vals: dict[str, Any] = {"counted": counted}
        if note:
            vals["note"] = note
        odoo.call("h2o.cash.handover", "write", ids=[handover_id], vals=vals)
        odoo.call("h2o.cash.handover", "action_approve", ids=[handover_id])
        handover = odoo.read("h2o.cash.handover", [handover_id], HANDOVER_FIELDS)[0]
        return clean(handover, "trip_id", "driver_id", "approved_by")

    @tool(WRITE, "Create monthly statements")
    def create_monthly_statements(
        month: Annotated[str | None, Field(description="YYYY-MM. Default: last month")] = None,
        customer_ids: Annotated[list[int] | None, Field(description="Default: every customer on account")] = None,
    ) -> dict[str, Any]:
        """Invoice customers on account for everything delivered in a month and not invoiced yet,
        one posted invoice per customer. Changes data."""
        if month:
            if not re.fullmatch(r"\d{4}-\d{2}", month):
                raise ToolError(f"Use the month as YYYY-MM, not {month!r}.")
            first_day = f"{month}-01"
        else:
            first_day = (today().replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()
        vals: dict[str, Any] = {"month": first_day}
        if customer_ids:
            vals["partner_ids"] = [[6, 0, customer_ids]]
        wizard_ids = odoo.call("h2o.statement.wizard", "create", vals_list=[vals])
        action = odoo.call("h2o.statement.wizard", "action_create_statements", ids=wizard_ids)
        if action.get("type") != "ir.actions.act_window":
            return {"month": first_day[:7], "invoices": [], "message": "Nothing left to invoice for this month."}
        invoices = odoo.search_read(
            "account.move", action["domain"], ["name", "partner_id", "invoice_date", "amount_total"], order="name")
        return {"month": first_day[:7], "invoices": [clean(i, "partner_id") for i in invoices]}

    @tool(WRITE, "Change a subscription")
    def change_subscription(
        subscription_id: int,
        action: Annotated[
            Literal["activate", "pause", "resume", "close", "generate_now"],
            Field(description="generate_now creates the next order right away"),
        ],
    ) -> dict[str, Any]:
        """Activate, pause, resume or close a recurring delivery, or create its next order now.
        Changes data."""
        method = "action_h2o_generate_now" if action == "generate_now" else f"action_{action}"
        odoo.call("h2o.subscription", method, ids=[subscription_id])
        subscription = odoo.read(
            "h2o.subscription", [subscription_id],
            ["name", "partner_id", "state", "frequency", "weekday_id", "next_date", "order_count"])[0]
        return clean(subscription, "partner_id", "weekday_id")

    return server
