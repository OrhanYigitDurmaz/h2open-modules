# H2Open modules

Custom Odoo 20 Community modules for H2Open, an ERP for a water delivery
business in Türkiye: returnable 19 L bottles (damacana) with deposits, plus
non-returnable packaged water (5 L, 0.5 L, ...).

Every module extends Odoo's standard apps (Contacts, Sales, Inventory,
Invoicing, Fleet, Employees) instead of rebuilding them. The design decisions
live in the H2Open Design Decisions doc; [`SPEC.md`](SPEC.md) is the technical
contract between the modules (models, fields, groups, APIs).

## Modules

| Module | What it does | Depends on (H2Open) |
| --- | --- | --- |
| `h2o_base` | H2Open menu root, security groups (driver, dispatcher, accountant, manager), shared settings | none |
| `h2o_customer` | Zones, customer type, preferred delivery days, delivery notes, payment mode | `h2o_base` |
| `h2o_push` | FCM device tokens per user and push sending (HTTP v1 API) | `h2o_base` |
| `h2o_container` | Returnable product settings, bottle ledger, per-customer bottle and deposit balances, deposit accounting | `h2o_customer` |
| `h2o_order` | Delivery fields on sale orders (channel, date, time window), bottle/deposit handling on order lines | `h2o_customer`, `h2o_container` |
| `h2o_subscription` | Recurring delivery plans that generate sale orders | `h2o_order` |
| `h2o_dispatch` | Vehicles, routes, daily trips and stops | `h2o_order` |
| `h2o_driver` | JSON API for the driver app (login, trips, stops, deliver, collect empties, payments, SIP credentials) | `h2o_dispatch`, `h2o_push` |
| `h2o_stock` | Trip load-out and return as stock pickings, vehicle stock locations | `h2o_container`, `h2o_dispatch` |
| `h2o_billing` | Invoicing from stops, monthly statements, driver cash handover | `h2o_order`, `h2o_dispatch` |
| `h2o_telephony` | Asterisk link: caller lookup, call log, SIP accounts, wake-up push for the driver app | `h2o_customer`, `h2o_push` |
| `h2o_reporting` | Dashboards: deliveries, bottles outstanding, cash collected, route performance | all of the above |

## Running locally

```bash
# Odoo 20 source checkout next to this repo
./odoo-bin -d h2open --addons-path=addons,../h2open-modules -i h2o_reporting
# run the tests of one module
./odoo-bin -d h2open_test --addons-path=addons,../h2open-modules \
    -i h2o_container --test-enable --stop-after-init
```

Installing `h2o_reporting` pulls in every other module.
