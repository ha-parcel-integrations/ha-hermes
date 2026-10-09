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
  the token pair is persisted. An HTML 403 from the gateway arrives before the
  password is checked, so it is never a reauth prompt — branch on the body, not
  the status (error key `request_refused`, raised as
  `HermesAccountCompatibilityError`). Its cause is **not** knowable from the
  response: a rotated app key, a WAF/geo/IP block and a transient refusal all
  look identical, so never tell the user to "wait for a release" — the client
  logs the status + content-type + a truncated body snippet (`_snippet`) so a
  user's debug log can tell them apart. The account coordinator raises
  `ConfigEntryAuthFailed` itself.
  `sender` is `atg.companyName` — **ATG is the Auftraggeber, the shipper**, not
  the delivering partner (four real parcels named Flaconi, QVC, Deutsche Telekom
  and "Privatversand"). `pickup_point` is built from `address` **only when
  `addressType == "PARCELSHOP"`** — that one block describes whatever the
  destination is, so reading it unconditionally would publish the receiver's own
  name as a pickup point. `planned_from`/`planned_to`, `weight`, `dimensions`
  stay `None`: `bookedEdl.deliveryDate` is a *requested* day (two days off on a
  real parcel), not a forecast. `delivered` is `metaInformation.delivered`, never
  inferred from the status — but it is **suppressed while the status is
  `at_pickup_point`**, so a parcel on a shop counter is never announced as
  delivered. A thin `IN_UNKNOWN` element has no `status` block and must
  normalise to `unknown`.
- **Two status maps, never merged** — `TRACKING_STATUS_MAP` (English) and
  `ACCOUNT_STATUS_MAP` (German) in `status.py`, both under the field name
  `parcelStatus`. The `EDL_*`/`HBX_*`/`TAN_*`/`INVALID_*` account families stay
  unmapped on purpose.
  - **`ZUGESTELLT_PAKETSHOP` is `at_pickup_point`, not `delivered`** — it means
    "abholbereit"; a real parcel reached `VOM_PAKETSHOP_ABGEHOLT` two hours
    later. Do not "correct" it back because the word reads as delivered.
  - **The account vocabulary cannot be enumerated from the app.** A live parcel
    returned `INT_ZUGESTELLT_ABLAGEORT`, which appears nowhere in the app
    binary. Map each new code explicitly as it surfaces; never pattern-match on
    `ZUGESTELLT`, which would swallow a negated form.
- **Every account parcel is treated as incoming — unverified, not decided.**
  Hermes' app has three lists (`ShipmentListType` = `INCOMING`/`OUTGOING`/
  `RETURN`), but no captured parcel was ever outgoing and the response carries
  no `shipmentListType`, so there is no confirmed discriminator. Defaulting to
  incoming is the suite's safe default (an unrecognised value must never make
  parcels disappear), *not* evidence Hermes has no outgoing parcels — a user who
  sends parcels would currently get the full incoming event set for them. Do not
  invent a discriminator from `shipmentType`'s `IN_` prefix without a real
  outgoing parcel; see `carrier-research/hermes/api/account.md`.
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
