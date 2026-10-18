# H2Open MCP server

An [MCP](https://modelcontextprotocol.io) server that lets Claude (Claude Code,
Claude Desktop or any MCP client) work with H2Open the way a dispatcher or
manager does: find a customer, take a phone order, plan tomorrow's trips,
record a delivery a driver phoned in, count a driver's cash, look at the day.

Every tool goes through the `h2o_*` modules' own methods and wizards (the same
code as the buttons in Odoo), never raw field edits, so the business rules
apply: deposits are added to orders, bottles are written to the ledger,
closing a trip moves the stock and creates the cash handover. It talks to Odoo
over the JSON-2 API with an API key, so Claude can only see and do what that
Odoo user can.

## Tools

| Tool | Changes data | What it does |
| --- | --- | --- |
| `find_customers` | | Search by name, phone (any format), email or street |
| `customer_overview` | | Contact and delivery details, delivery days, bottles held, open orders, subscriptions, bottle ledger, unpaid invoices |
| `list_products` | | Water and bottle products with prices |
| `list_routes` | | Routes with their zones, days, driver and vehicle |
| `list_delivery_orders` | | Delivery orders by date, delivery state, zone or customer |
| `create_phone_order` | yes | The New phone order screen: create and confirm a delivery order |
| `plan_trips` | yes | The Plan Trips wizard: build a day's trips and stops |
| `list_trips` | | A day's trips with progress, bottles and cash |
| `get_trip` | | One trip with its stops in order |
| `trip_action` | yes | Load, start, close, cancel or re-plan a trip |
| `deliver_stop`, `fail_stop`, `skip_stop` | yes | Record what happened at a stop |
| `day_overview` | | Trips, totals, failed stops, orders still to plan, cash to count |
| `bottles_outstanding` | | Who holds the most bottles, total bottles and deposit held |
| `delivery_report` | | Deliveries, success rate, bottles and cash by day, route, driver, zone... |
| `list_cash_handovers`, `approve_cash_handover` | approve: yes | Count and approve drivers' cash |
| `create_monthly_statements` | yes | Invoice customers on account for a month |
| `change_subscription` | yes | Activate, pause, resume or close a subscription, or create its next order now |

Tools that change data are marked as such for the MCP client, so Claude Code
asks before running them unless you allow them.

## Setup

1. **API key.** In Odoo, open your avatar menu > Preferences > Account
   Security > New API Key. Use the user whose rights Claude should have (a
   dispatcher or manager). Administrators can make keys that never expire;
   other users are limited by the "API Keys maximum duration" of their groups
   (a group field shown in developer mode), 1 day by default.

2. **Install** (Python 3.12+). With [uv](https://docs.astral.sh/uv/) nothing
   needs installing: the commands below run it from this folder. Without uv:
   `pip install ./mcp_server` puts an `h2open-mcp` command on your path.

3. **Add it to Claude Code.** This repo has a `.mcp.json`, so Claude Code
   started in the repo offers the `h2open` server. It reads three variables
   from your environment:

   ```bash
   export H2OPEN_URL=http://localhost:8069
   export H2OPEN_DB=h2open
   export H2OPEN_API_KEY=<the key>
   ```

   Or add it for every project:

   ```bash
   claude mcp add h2open --scope user \
     -e H2OPEN_URL=http://localhost:8069 -e H2OPEN_DB=h2open -e H2OPEN_API_KEY=<the key> \
     -- uv run --directory ~/Projects/h2open/h2open-modules/mcp_server h2open-mcp
   ```

   Claude Desktop: add the same command, arguments and variables under
   `mcpServers` in `claude_desktop_config.json`.

`H2OPEN_TZ` (default `Europe/Istanbul`) sets what "today" means.

## Tests

```bash
cd mcp_server
uv run --extra test pytest            # helper tests; live tests are skipped
```

`tests/test_live.py` runs a whole day (phone order, planning, deliveries, cash
count, reports) against a real Odoo with the `h2o_*` demo data when
`H2OPEN_URL`, `H2OPEN_DB` and `H2OPEN_API_KEY` are set, plus
`H2OPEN_TEST_DRIVER_KEY` (a driver's key) for the access test. It changes
data, so use a throwaway database. CI does not run these tests.
