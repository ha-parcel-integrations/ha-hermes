# Working in this repository

Home Assistant custom integration for **Hermes** parcel tracking. Distributed via
HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
Account-less (`track_parcel` / `untrack_parcel` services). No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| ship anything while below 1.0.0 (no real parcel run through yet) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client) | *Deliberate skill divergences* |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific notes

This is **Hermes Germany — "Hermes Paket"** (mass-market). Two other Hermes
surfaces exist and are deliberately **not** used — do not "fix" the integration
to use them:
- `myhes.de/api/request/auftragsdaten` — that's Hermes *Einrichtungs-Service*
  (2-man / furniture), a different niche service. Not Paket.
- the app account API (`mobile-app-api.a0930.prd.hc.de`) — richer (auto-discovers
  parcels) but walled behind a static **`Api-Key` embedded in the app** (empty
  403 without it). That's the refused *shared-extracted-secret* class
  (bpost/Evri failure mode) — do not ship it.

### The endpoint
- **Keyless, code-only** (no key, Bearer or postcode):
  `GET https://api.my-deliveries.de/tnt/v2/shipments/search/{number}` (14 digits)
  — the myhermes.de widget's API, cross-checked against `itsvic-dev/deliveries`
  and `dbalan/hermes`.
- Headers (`api.py`): `Accept: application/json`, `X-Language: de`, browser-ish
  `User-Agent`, `Referer: https://www.myhermes.de/` (keyless; UA/Referer just
  avoid edge heuristics). Optional `X-ZipCode` exists but is **not** required or
  sent.
- **"Unknown code": HTTP 404** (not found / not yet scanned) **and HTTP 400**
  (malformed) are both normal "no data yet" → `async_get_parcel` returns `None`.
  A **5xx** / other non-2xx raises `HermesApiError`. Probed 2026-07-23: 14 digits
  → 404, 12 → 400, no bot wall.
- **Response is a JSON array** of shipments (we track one code → element 0). Empty
  array is also `None`.

### Payload & status map
```
{ "barcode": str,
  "parcelProgress": [ {"timestamp": iso|null, "status": str,
                       "parcelStatus": str, "historyText": str|null}, ... ] }
```
- `parcelProgress` is **newest event first**; current status is
  `parcelProgress[0].parcelStatus`.
- **Map the stable English `parcelStatus`** (`_STATUS_MAP`), never the localised
  `status` / `historyText` (those become `raw_status`). Timestamps are ISO 8601
  (`parse_iso` handles `Z` and naive values).
- **Fields Hermes does not expose** (so the `None`s are intentional): `sender`,
  `receiver`, `pickup_point`, `weight`, `dimensions`. `planned_from` is read
  **defensively** from a top-level `eta` / `deliveryForecast` (scalar only) — the
  confirmed model has no ETA but the widget reads one; `planned_to` always `None`.

**Release blocker (pre-1.0):** endpoint/auth/payload/status confirmed by three
independent clients, but **no real 14-digit parcel has been run through it** — the
exact top-level nesting and full `parcelStatus` vocabulary are the last unknowns.
Treat `tests/payloads.py` as evidence-based, not observed. See `TODO.md`.

## Options and reloads — account-less model

The options flow is one sectioned form; changes apply without a restart.
Account-less carriers (this one) use the **update-listener** model (retunes
`coordinator.update_interval` + `async_request_refresh()`). Account-based carriers
instead call `async_schedule_reload` with **no** listener (combining the two is
deprecated, error in HA 2026.12+). The user-tunable poll interval is a deliberate
HACS divergence (see CONVENTIONS.md).

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`) | no |

`parcels.py` is free of I/O and HA objects so the per-carrier part stays
unit-testable. Config: `ConfigEntry.runtime_data` (typed, no `hass.data`),
`PARALLEL_UPDATES = 0`, coordinator takes `config_entry=entry`.
`aiohttp.ClientError` is caught **per parcel** in the gather loop (one bad parcel
doesn't fail the poll) but **not** around the whole update (coordinator wraps
that). Entities: `has_entity_name` + `translation_key`, `icons.json`, translated
units, `_attr_attribution`, `_unrecorded_attributes` on anything with a parcel
list or `raw`. Over-redact diagnostics.

## Tests on Windows

`tests/conftest.py` carries two Windows-only shims (no-ops elsewhere):
`disable_socket` is neutralised (Windows event loops need AF_INET socketpairs;
the 127.0.0.1 allowlist stays) and HA's `AsyncResolver` is swapped for
`ThreadedResolver` (aiodns refuses the Proactor loop). Do not remove them
"because CI passes" — CI is Linux, development is Windows.

## Running tests

```
python -m pytest tests/ --cov=custom_components.hermes
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; `docs/api/` is gitignored (local reverse-engineering notes).
