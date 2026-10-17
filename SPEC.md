# H2Open technical spec

The contract between the `h2o_*` modules: what each module owns, the exact
model and field names other modules rely on, and the hooks between them.
Business decisions come from the H2Open Design Decisions doc; this file turns
them into names. When a module needs something from a lower module that is
not listed here, add it to the lower module and to this file.

Target: **Odoo 20.0 Community**, Türkiye (TRY), single company with several
warehouses allowed. All field names added to standard models start with
`h2o_`. Python and XML strings are written in English; Turkish comes through
translations.

## Layers

```
h2o_base
├── h2o_customer ── h2o_container ── h2o_order ─┬─ h2o_subscription
│                                                └─ h2o_dispatch ─┬─ h2o_driver (+ h2o_push)
├── h2o_push ── h2o_telephony                                     ├─ h2o_stock (+ stock)
│                                                                 └─ h2o_billing (+ account)
└──────────────────────────────── h2o_reporting (everything)
```

A module may only use modules on its path back to `h2o_base`.

## Odoo 20 conventions used here

* Access rights live in `security/ir.access.csv` (model `ir.access`, not
  `ir.model.access`). Columns: `id,name,model_id,group_id/id,operation,domain`.
  `model_id` is the model name (`h2o.trip`), `operation` a subset of `crud`.
  A row **with** a group grants that group the operations on records matching
  `domain` (empty = all). A row **without** a group is a global restriction
  (replaces old global record rules). There are no separate `ir.rule` files.
* Groups use `privilege_id` (model `res.groups.privilege`) and `user_ids`.
  Users have `group_ids`.
* SQL constraints: `_name_uniq = models.Constraint('UNIQUE(name)', 'msg')`;
  indexes: `models.Index(...)`.
* List views use `<list>`; visibility with `invisible="state != 'draft'"`.
* Settings: inherit `h2o_base.res_config_settings_view_form` and add a
  `<block>` inside `//app[@name='h2o_base']`.
* App APIs use `odoo.addons.h2o_base.controllers.api.h2o_route(path, methods=...)`:
  `type='json2'` (plain JSON body in, JSON out), `auth='bearer'` with the
  `h2o_app` API key scope. Paths live under `/h2o/api/v1/...`.
* Tests are tagged `@tagged('post_install', '-at_install')` and live in
  `tests/`. Every module ships tests for its main flows.
* Manifest version `20.0.1.0.0`, `license: LGPL-3`, `author: H2Open`,
  `category: H2Open`.

## h2o_base (done)

Depends: `base`, `mail`.

* Groups (all under privilege `h2o_base.res_groups_privilege_h2open`):
  * `h2o_base.group_h2o_driver` (implies `base.group_user`)
  * `h2o_base.group_h2o_accountant` (implies `base.group_user`)
  * `h2o_base.group_h2o_dispatcher` (implies driver)
  * `h2o_base.group_h2o_manager` (implies dispatcher and accountant; admin is a member)
* Menus: `h2o_base.menu_h2o_root` with sections `menu_h2o_operations` (10),
  `menu_h2o_customers` (20), `menu_h2o_billing` (30), `menu_h2o_reporting`
  (40), `menu_h2o_config` (100).
* `h2o.weekday`: `name` (translated), `code` (0 = Monday … 6 = Sunday).
  XML ids `h2o_base.weekday_mon` … `weekday_sun`.
  `env['h2o.weekday']._h2o_from_date(date)`.
* `res.company`: `h2o_order_cutoff_hour` (float, default 16.0),
  `h2o_app_token_days` (int, default 30). Both on settings.
* `res.users`: `_h2o_app_roles()` → list of `manager|dispatcher|accountant|driver`,
  `_h2o_issue_app_token(device_name)` → API key string, `_h2o_app_profile()` → dict.
* API: `POST /h2o/api/v1/login {login, password, device_name}` →
  `{token, user}`; `POST /h2o/api/v1/logout`; `GET|POST /h2o/api/v1/me`.

## h2o_customer

Depends: `h2o_base`, `contacts`.

* `h2o.zone`: `name`, `code`, `active`, `company_id`, `state_id` (il),
  `district_names` (Char, comma-separated ilçe/mahalle names), `zip_codes`
  (Char, comma-separated), `weekday_ids` (m2m `h2o.weekday`, delivery days),
  `partner_ids` (o2m on `h2o_zone_id`), `partner_count`, `color`.
  `_h2o_match_partner(partner)` → zone or empty, matching zip first, then
  district names against `partner.city` / `street2`, within `state_id`.
* `res.partner`:
  * `h2o_customer_type` selection `home|office|reseller` (empty = not a water customer)
  * `h2o_zone_id` (m2o `h2o.zone`), set automatically from the address when
    empty (onchange and on create/write of address fields)
  * `h2o_weekday_ids` (m2m `h2o.weekday`, preferred delivery days; empty = zone days)
  * `h2o_delivery_notes` (Text: floor, door code, where to leave bottles)
  * `h2o_floor` (Integer), `h2o_has_elevator` (Boolean)
  * `h2o_payment_mode` selection `cash|card|account` (default `cash`; `account` = monthly invoice)
  * `_h2o_delivery_weekdays()` → own days or zone days
* Menus: Customers (`menu_h2o_customers` → partner list filtered on
  `h2o_customer_type != False`), Configuration → Zones.
* Partner form: a "Water delivery" page with the fields above.

## h2o_container

Depends: `h2o_customer`, `product`, `account`.

* `product.template`:
  * `h2o_product_kind` selection:
    `water_returnable` (filled 19 L bottle),
    `water_packaged` (non-returnable 5 L, 0.5 L …),
    `container` (the empty returnable bottle, dispenser),
    `deposit` (deposit service product).
    Empty = unrelated product.
  * `h2o_volume` (Float, litres)
  * `h2o_container_product_id` (m2o `product.product`, kind `container`):
    on a `water_returnable` product, the bottle it comes in.
  * `h2o_deposit_product_id` (m2o `product.product`, kind `deposit`):
    on a `container`, the deposit charged per bottle (price = its list price).
* `h2o.container.move` (the bottle ledger, `mail.thread`): `name` (sequence
  `CM/2026/00001`), `date`, `partner_id` (commercial partner, required),
  `address_id` (delivery address), `product_id` (container product, required),
  `qty_out` (bottles given to the customer, ≥ 0), `qty_in` (bottles taken back,
  ≥ 0), `deposit_amount` (Monetary, signed: + charged, − refunded),
  `currency_id`, `company_id`, `source` selection
  `delivery|adjustment|opening|closing`, `origin` (Char, e.g. order or stop
  name), `origin_ref` (Reference to any model), `state` `draft|done|cancel`,
  `note`. Only `done` moves count. Actions: `action_done`, `action_cancel`,
  `action_draft`. API for other modules:
  `env['h2o.container.move']._h2o_record(partner, product, qty_out=0, qty_in=0, deposit_amount=0.0, source='delivery', origin='', origin_ref=False, address=False, date=None)`
  → creates a `done` move and returns it.
* `h2o.container.balance` (SQL view, `_auto = False`): `partner_id`,
  `product_id`, `qty` (out − in), `deposit_amount`, `company_id`.
* `res.partner`: `h2o_bottle_balance` (Integer, computed from done moves of
  the commercial partner, all container products), `h2o_deposit_balance`
  (Monetary), `h2o_container_move_count`, smart button to the ledger.
  `_h2o_bottle_balance_by_product()` → `{product: qty}`.
* Deposit accounting: `res.company.h2o_deposit_account_id` (liability
  account, on settings). Invoice lines of a `deposit` product use that
  account instead of the income account (override on `account.move.line`).
* Data (noupdate): products `product_water_19l` (water_returnable, 19 L),
  `product_bottle_19l` (container), `product_deposit_19l` (deposit),
  `product_water_5l` and `product_water_05l` (water_packaged), all under
  product category `product_category_water`.
* Menus: Customers → Bottle ledger, Bottle balances; Configuration → Water products.

## h2o_order

Depends: `h2o_customer`, `h2o_container`, `sale`.

* `sale.order`:
  * `h2o_is_delivery` (Boolean, true when any line is a water/container product)
  * `h2o_channel` selection `phone|portal|subscription|driver|other` (default `phone`)
  * `h2o_delivery_date` (Date), `h2o_time_window` selection `any|morning|afternoon|evening` (default `any`)
  * `h2o_zone_id` (related `partner_shipping_id.h2o_zone_id`, stored)
  * `h2o_empties_expected` (Integer, empties the customer will hand back)
  * `h2o_delivery_state` selection `to_plan|planned|delivered|failed|cancelled`
    (default `to_plan`; set by `h2o_dispatch`)
  * `h2o_delivery_notes` (related to the shipping address)
  * `action_h2o_update_deposit_lines()`: adds or updates one deposit line per
    container: qty = max(0, returnable qty − empties expected), so a deposit
    is charged only when the customer ends up holding more bottles. Removes
    the line when the qty drops to 0. Called automatically on confirm.
  * `_h2o_returnable_qty_by_container()` → `{container product: qty}` from lines.
* `res.partner._h2o_next_delivery_date(from_datetime=None)` → the next date on
  one of the partner's delivery weekdays, today allowed only before the
  company cut-off hour (company time zone). Default for `h2o_delivery_date`.
* Pricing per customer type: `res.company.h2o_pricelist_home_id`,
  `h2o_pricelist_office_id`, `h2o_pricelist_reseller_id` (settings). Setting
  `h2o_customer_type` on a partner sets its `property_product_pricelist`
  when that company pricelist is configured.
* Quick phone order wizard `h2o.quick.order` (+ `h2o.quick.order.line`):
  partner, shipping address, lines (product, qty), empties expected, date,
  time window, note → creates and confirms a `sale.order` with
  `h2o_channel='phone'`. Menu Operations → New phone order.
* Menus: Operations → Delivery orders (sale orders with `h2o_is_delivery`).

## h2o_subscription

Depends: `h2o_order`.

* `h2o.subscription` (`mail.thread`): `name` (sequence `SUB/00001`),
  `partner_id`, `address_id`, `line_ids` (`h2o.subscription.line`:
  `product_id`, `qty`), `frequency` selection `weekly|biweekly|monthly`,
  `weekday_id` (m2o `h2o.weekday`), `next_date`, `time_window`,
  `empties_expected`, `state` `draft|active|paused|closed`, `order_ids`,
  `order_count`, `company_id`, `note`.
* `res.company.h2o_subscription_lead_days` (default 1, settings).
* Cron `_cron_h2o_generate_orders()`: for active subscriptions with
  `next_date <= today + lead days`, create and confirm a `sale.order`
  (`h2o_channel='subscription'`, `h2o_delivery_date=next_date`,
  `h2o_subscription_id`), then advance `next_date`. Idempotent per date.
* `sale.order.h2o_subscription_id`.
* Menus: Operations → Subscriptions.

## h2o_dispatch

Depends: `h2o_order`, `fleet`.

Drivers are `res.users` in `h2o_base.group_h2o_driver`.

* `fleet.vehicle`: `h2o_is_delivery_vehicle`, `h2o_capacity` (bottles),
  `h2o_driver_user_id` (m2o `res.users`).
* `h2o.zone`: `h2o_route_id` (default route).
* `h2o.route`: `name`, `code`, `active`, `company_id`, `zone_ids` (o2m on
  `h2o.zone.h2o_route_id`), `weekday_ids`, `vehicle_id`, `driver_id`
  (`res.users`), `trip_ids`.
* `h2o.trip` (`mail.thread`): `name` (sequence `TRIP/2026/0001`), `date`,
  `route_id`, `vehicle_id`, `driver_id`, `company_id`, `currency_id`,
  `state` `planned|loaded|on_road|closed|cancelled`, `stop_ids`,
  `stop_count`, `delivered_count`, `failed_count`, `load_qty` (full bottles
  loaded), `returned_full_qty`, `returned_empty_qty`, `cash_expected`
  (computed: sum of stop payments with method `cash`), `cash_handed_in`
  (Monetary, written by `h2o_billing`), `last_latitude`, `last_longitude`,
  `last_position_at`. Actions: `action_load`, `action_start`, `action_close`
  (all stops must be done, failed or skipped), `action_cancel`,
  `action_reset_planned`. Hooks other modules extend:
  `_h2o_on_loaded()`, `_h2o_on_started()`, `_h2o_on_closed()`.
* `h2o.stop`: `trip_id`, `sequence`, `partner_id` (delivery address),
  `commercial_partner_id` (related, stored), `order_id` (`sale.order`),
  `state` `pending|delivered|failed|skipped`, `failure_reason` selection
  `not_home|refused|no_access|no_payment|other`, `failure_note`,
  `line_ids` (`h2o.stop.line`: `product_id`, `sale_line_id`, `qty_planned`,
  `qty_delivered`), `empties_collected` (Integer),
  `empties_product_id` (container product, default the 19 L bottle),
  `payment_method` selection `cash|card|account|none`, `payment_amount`
  (Monetary), `amount_due` (computed from the order total for the delivered
  quantities), `signature` (Binary), `photo` (Binary), `latitude`,
  `longitude`, `done_at` (Datetime), `note`, `time_window` (related order).
  * `action_deliver(vals=None)`: optional `vals` with `lines`
    (`[{'product_id', 'qty_delivered'}]`, defaults to planned),
    `empties_collected`, `payment_method`, `payment_amount`, `signature`,
    `photo`, `latitude`, `longitude`, `note`. Writes delivered quantities to
    `sale.order.line.qty_delivered`, records the bottle ledger through
    `h2o.container.move._h2o_record` (qty_out per container from delivered
    returnable products, qty_in from empties, deposit from delivered deposit
    lines), sets `order_id.h2o_delivery_state='delivered'`, then calls
    `_h2o_on_delivered()` (hook for billing).
  * `action_fail(reason, note=None)` → `failed`, order back to `to_plan`
    (so it is planned again), hook `_h2o_on_failed()`.
  * `action_skip()` → `skipped`, order back to `to_plan`.
* `sale.order`: `h2o_stop_ids`, `h2o_trip_id` (last stop's trip).
* Planning: wizard `h2o.trip.plan` (`date`, `route_ids`): for every route
  running on that weekday, create (or reuse) the `planned` trip and add a stop
  for every confirmed `to_plan` order of the route's zones with
  `h2o_delivery_date <= date`, ordered by zone then partner; the order goes to
  `planned`. `h2o.trip._h2o_plan_day(date, routes=None)` does the work.
* Access: drivers read their own trips (`driver_id = user.id`) and read and
  write the stops of those trips; dispatchers do everything.
* Menus: Operations → Trips (kanban/list/form with editable stops), Stops;
  Configuration → Routes, Vehicles.

## h2o_driver

Depends: `h2o_dispatch`, `h2o_push`.

JSON API for the driver app, all with `h2o_route` under `/h2o/api/v1/driver/`.
Every route checks the user is a driver and only touches their own trips.

* `GET trips?date=YYYY-MM-DD` (default today) → trips with stop counts.
* `GET trips/<id>` → trip with ordered stops (address, phone, notes, floor,
  time window, lines, bottle balance, amount due, payment mode, coordinates).
* `POST trips/<id>/start`, `POST trips/<id>/close`.
* `POST stops/<id>/deliver` body as `h2o.stop.action_deliver` vals
  (signature/photo base64).
* `POST stops/<id>/fail {reason, note}`, `POST stops/<id>/skip`.
* `POST position {latitude, longitude, trip_id}` → updates trip last position.
* `POST stops/reorder {trip_id, stop_ids}` → driver may resequence pending stops.
* Errors: 4xx JSON with a message for bad state or foreign records.
* Pushes (through `h2o_push`): to the driver when a stop is added to or
  removed from their trip in progress (`type: 'trip_changed'`).

## h2o_push

Depends: `h2o_base`.

* `h2o.push.device`: `user_id`, `token` (unique), `platform` `android|ios`,
  `app` `driver|customer`, `device_name`, `last_seen`, `active`.
* Settings (system parameters, on the H2Open settings page): FCM project id
  `h2o_push.fcm_project_id`, service account JSON `h2o_push.fcm_service_account`.
* `env['h2o.push.device']._h2o_send(users, data, notification=None, priority='high', ttl=60, app=None)`:
  sends an FCM HTTP v1 message to every active device of the users (data
  values as strings), with an OAuth2 access token from the service account
  (JWT RS256, token cached until expiry). Unregistered tokens are
  deactivated. Never raises on network errors; logs and returns a result
  dict. Tests mock the HTTP calls.
* `h2o.push.log`: `user_id`, `device_id`, `data` (Json), `state`
  `sent|failed`, `error`, `create_date`. Kept 30 days (cron cleanup).
* API: `POST /h2o/api/v1/push/register {token, platform, app, device_name}`,
  `POST /h2o/api/v1/push/unregister {token}`.

## h2o_telephony

Depends: `h2o_push`, `contacts`.

Asterisk runs on the office PC, reached over WireGuard. Odoo never records calls.

* Settings (system parameters): ARI URL, ARI user and password, shared secret
  for Asterisk → Odoo calls (`h2o_telephony.asterisk_secret`), SIP domain,
  WSS URL given to the app (`wss://<vps>/ws`), SIP credential lifetime hours
  (default 12).
* `h2o.sip.account`: `user_id` (unique), `extension` (unique), `active`,
  `password_expires_at`; the password itself is generated per login and
  never stored in clear in a readable field.
* `h2o.call`: `direction` `inbound|outbound|internal`, `caller_number`,
  `called_number`, `partner_id`, `user_id`, `start`, `answer`, `end`,
  `duration` (seconds), `state` `ringing|answered|missed|ended`,
  `asterisk_uniqueid`.
* Asterisk → Odoo endpoints (`type='json2'`, `auth='none'`, header
  `X-H2O-Secret` must equal the shared secret):
  `POST /h2o/telephony/v1/lookup {number}` → `{name, partner_id}` for caller
  ID (matches Turkish numbers in any format: +90, 0, spaces);
  `POST /h2o/telephony/v1/event {uniqueid, event: ring|answer|hangup, ...}` →
  maintains `h2o.call` and notifies dispatchers on ring (bus notification
  with the customer's name and a link);
  `POST /h2o/telephony/v1/wake {extension, call_id, caller}` → high-priority
  push `{type: 'incoming_call', ...}` to the driver app devices of that
  extension's user; `POST /h2o/telephony/v1/cancel {extension, call_id}` →
  push `{type: 'call_cancelled'}`.
* App endpoint: `POST /h2o/api/v1/sip/credentials` (bearer) → generates a
  fresh password, pushes the PJSIP auth/aor/endpoint for the extension to
  Asterisk through ARI dynamic config (`/ari/asterisk/config/dynamic/res_pjsip/...`,
  transport WSS, WebRTC on, codec alaw, ICE on), returns
  `{username, password, domain, wss_url, expires_at, ice_servers: []}`.
* Menus: Operations → Calls (dispatchers); Configuration → SIP accounts.

## h2o_stock

Depends: `h2o_container`, `h2o_dispatch`, `stock`.

Stock moves happen once per trip, never per stop.

* `h2o.route.h2o_warehouse_id` (default company warehouse).
* `fleet.vehicle.h2o_location_id`: internal location per delivery vehicle,
  created automatically under the warehouse's view location ("WH/Vehicles/34 ABC 123").
* `h2o.trip`: `h2o_load_line_ids` (`h2o.trip.load.line`: `product_id`,
  `qty_planned` (from stops), `qty_loaded`, `qty_delivered` (from stops),
  `qty_returned`), `h2o_picking_ids`.
  * On load (`_h2o_on_loaded`): one picking warehouse → vehicle for
    `qty_loaded` (defaults to planned).
  * On close (`_h2o_on_closed`): one picking vehicle → customers for
    delivered quantities, one picking customers → vehicle for collected
    empties (container products), and one picking vehicle → warehouse for
    everything left on the vehicle. All validated automatically.
* Water and container products are storable (`is_storable = True`) when
  `h2o_stock` is installed.
* Menus: Operations → Vehicle stock.

## h2o_billing

Depends: `h2o_order`, `h2o_dispatch`, `account`.

* `res.company`: `h2o_cash_journal_id` (driver cash), `h2o_card_journal_id`,
  both on settings.
* On delivery (`h2o.stop._h2o_on_delivered`): for customers with payment
  mode `cash` or `card`, create and post the invoice for the delivered order
  quantities; if a payment was collected, register it on the matching journal
  and reconcile. Customers on `account` are not invoiced per delivery.
* Monthly statements: cron `_cron_h2o_monthly_invoices()` on the 1st, and a
  manual wizard `h2o.statement.wizard` (month, partners): one invoice per
  `account` customer for all delivered, not yet invoiced orders of the month.
  `account.move.h2o_statement_month` (Date, first day of month).
* `account.move.h2o_stop_id`.
* `h2o.cash.handover` (`mail.thread`): `name`, `trip_id`, `driver_id`,
  `date`, `currency_id`, `expected` (trip `cash_expected`), `counted`,
  `difference` (computed), `state` `draft|approved`, `approved_by`,
  `note`. `action_approve` writes `trip_id.cash_handed_in`. One per trip.
  Created automatically when a trip closes.
* Menus: Billing → Cash handovers, Monthly statements, Invoices.

## h2o_reporting

Depends: every module above.

* `h2o.report.delivery` (SQL view over `h2o.stop`): date, trip, route,
  driver, vehicle, zone, partner, customer type, state, failure reason,
  bottles delivered, empties collected, payment method, payment amount.
* Actions with pivot/graph/list views: Deliveries per day, Bottles
  outstanding (`h2o.container.balance`), Cash collected (stops + handovers),
  Route performance (stops per trip, success rate).
* Menus under Reporting.
