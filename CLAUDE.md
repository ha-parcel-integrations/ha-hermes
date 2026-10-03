# Working in this repository

Home Assistant custom integration for **Hermes** parcel tracking. Distributed via
HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
Tracking codes or a Hermes account. No DTO layer.

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

This is **Hermes Germany — "Hermes Paket"** (mass-market), with two sources in
one domain (`entry.data[CONF_SOURCE]`, every read defaulting to tracking so
1.1.x entries keep working). The *Einrichtungs-Service* (2-man / furniture) is a
different niche service — do not "fix" the integration to use it.

- **`tracking/`** — the keyless code-based source. Endpoint/auth/payload/status
  are confirmed by three independent clients and a real 14-digit parcel.
  Account-less (`track_parcel` / `untrack_parcel` services, tracking hubs only).
  The sender is populated when Hermes provides it; `receiver`, `pickup_point`,
  `weight`, `dimensions` stay `None`; `planned_from` is read defensively.
- **`account/`** — the logged-in inbox source. Login identifier is the account
  **username**, not an email; unique id `account:<lowercased username>`. Only
  the token pair is persisted. A rejected app credential is an HTML 403 from the
  gateway before the password is checked: it is a *compatibility* failure
  (`update_required`), never a reauth prompt — branch on the body, not the
  status. The account coordinator raises `ConfigEntryAuthFailed` itself.
  `sender`, `planned_from`/`planned_to`, `pickup_point`, `weight`, `dimensions`
  are always `None` (not in the response; `atg.companyName` is the delivery
  partner). `delivered` is `metaInformation.delivered`, never inferred. A thin
  `IN_UNKNOWN` element has no `status` block and must normalise to `unknown`.
- **Two status maps, never merged** — `TRACKING_STATUS_MAP` (English) and
  `ACCOUNT_STATUS_MAP` (German) in `status.py`, both under the field name
  `parcelStatus`. The `EDL_*`/`HBX_*`/`TAN_*`/`INVALID_*` account families stay
  unmapped on purpose.
- Root `api.py` / `coordinator.py` / `parcels.py` are re-export shims for old
  import paths — keep them. Assigning module state through `parcels.py` does not
  reach the real module (it copies names); use `tracking.parcels`.
- `CAPABILITIES_BY_VARIANT` carries both sources' optional fields; keep it in
  agreement with the two normalisers.

## Running tests

```
python -m pytest tests/ --cov=custom_components.hermes
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file in the same commit;
the API reference now lives in the private `carrier-research/hermes/api/`,
not in this repo.
