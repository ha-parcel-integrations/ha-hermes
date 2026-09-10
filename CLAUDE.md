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

**Structure, options flow, dynamic polling and module layout are suite-wide**
and identical in every carrier — the authoritative spec is
[`ha-carrier-template/scaffold/CLAUDE.md`](https://github.com/ha-parcel-integrations/ha-carrier-template/blob/main/scaffold/CLAUDE.md).
This repo follows it exactly.

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

## Running tests

```
python -m pytest tests/ --cov=custom_components.hermes
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file in the same commit;
the API reference now lives in the private `carrier-research/hermes/api/`,
not in this repo.
