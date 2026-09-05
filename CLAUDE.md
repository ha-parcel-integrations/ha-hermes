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
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client) | *Deliberate skill divergences* |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**API mechanics live in `carrier-research/hermes/api/` (private research repo)** — the keyless
`api.my-deliveries.de` endpoint, its headers, the 404/400 "no data yet"
signalling, the `parcelProgress` payload and the `parcelStatus` vocabulary. Do
not duplicate them here.

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific decisions (integration only)

This is **Hermes Germany — "Hermes Paket"** (mass-market). Two other Hermes
surfaces exist and are deliberately **not** used — do not "fix" the integration to
use them:
- Hermes *Einrichtungs-Service* (2-man / furniture) — a different niche service,
  not Paket.
- the app account API — richer (auto-discovers parcels) but walled behind a static
  `Api-Key` embedded in the app. That's the refused **shared-extracted-secret**
  class (the bpost/Evri failure mode) — do not ship it.

The endpoint/auth/payload/status are confirmed by three independent clients
and by a real 14-digit parcel run through it (a live 200), so 1.0.0 is
shipped. The status vocabulary is still partial: any status we do not map
reports `unknown` (never a wrong status), so gaps degrade safely rather than
blocking a release. The sender is populated when Hermes provides it;
`receiver`, `pickup_point`, `weight`, and `dimensions` remain `None`.
`planned_from` is read defensively (a possible ETA the widget shows).
Reflected in `const.py`'s `CAPABILITIES` (feeds the docs site's comparison
table) — keep the two in agreement if that ever changes.

## Options and reloads — account-less model

The options flow is one sectioned form; changes apply without a restart.
Account-less carriers (this one) use the **update-listener** model (an
update listener calls `async_request_refresh()`). Account-based carriers
instead call `async_schedule_reload` with **no** listener (combining the two is
deprecated, error in HA 2026.12+). This is also the resume path after dynamic
polling has fully suspended (see below) — adding a parcel back triggers the
same refresh, which re-arms scheduling.

## Polling

Polling is dynamic and status-driven, unconditionally — there is no
user-facing interval option and never has been one since the
2026-08-30 conversion (`carrier-research/dynamic-polling.md`). The
coordinator recomputes its own cadence at the end of every refresh: a quiet
window (00:00–06:00 local, with catch-up anchors at each end), a 15-minute
hot tier when a tracked parcel is `out_for_delivery` (immediately, or from an
hour before `planned_from`), a 45-minute mid tier otherwise, and a full stop
(`update_interval = None`) when nothing is tracked or everything tracked is
delivered. See `coordinator.py`'s `_hottest_tier_minutes` /
`_next_update_interval` and `ha-carrier-template`'s
`example_carrier/coordinator.py` for the canonical shape this mirrors.

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

## Running tests

```
python -m pytest tests/ --cov=custom_components.hermes
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file in the same commit;
the API reference now lives in the private `carrier-research/hermes/api/`,
not in this repo.
