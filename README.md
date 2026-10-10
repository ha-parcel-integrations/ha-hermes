# Hermes Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-hermes.svg)](https://github.com/ha-parcel-integrations/ha-hermes/releases)
[![Downloads](https://img.shields.io/github/downloads/ha-parcel-integrations/ha-hermes/total.svg)](https://github.com/ha-parcel-integrations/ha-hermes/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Hermes](https://www.myhermes.de) (Germany, "Hermes Paket") parcels, from either of two sources:

- **Tracking codes** — no account needed; you enter the tracking number yourself, just like on the myhermes.de tracking page.
- **Hermes account** — log in with your Hermes account and your incoming parcels appear on their own, no codes to type.

For tracking codes: Most codes are 14 digits; some carry a single leading letter (e.g. `H1003660779926301068`) — enter it exactly as shown, including that letter.

Part of the [ha-parcel-integrations](https://ha-parcel-integrations.github.io/) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

> ### ℹ️ Status vocabulary still growing
>
> The endpoint is live and keyless, and unknown or badly-formatted numbers are
> handled correctly. The success payload and status vocabulary come from three
> independent sources that agree, confirmed against a real parcel. Any status
> we do not map reports **`unknown`** (never a wrong status) and logs a
> one-shot warning with a ready-made issue link —
> please [report it](https://github.com/ha-parcel-integrations/ha-hermes/issues/new?template=unrecognised_status.yml)
> so the mapping can be completed.

> ### ⚠️ The account source is unverified and may break
>
> The **Hermes account** source talks to the interface Hermes' own mobile app
> uses. It is not a public API: Hermes can change or withdraw it without
> notice, and the account source would then stop working until the integration
> is updated. It has been confirmed against one real account only. The
> expected delivery window is **always empty** for account parcels until a real
> parcel proves it. The **tracking code** source is unaffected.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Dynamic polling](#dynamic-polling)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Hermes parcels by tracking code — no account needed
- Or add a Hermes account and have its incoming parcels discovered automatically
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), the carrier's own status text and a tracking deep-link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the expected delivery windows
- `hermes.track_parcel` / `hermes.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- **Tracking codes:** a Hermes parcel and its tracking code (from the shipping
  confirmation email or the missed-delivery card) — no account needed
- **Hermes account:** your Hermes account **username** and password. Note the
  username — the email address does not work as a login

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-hermes` as an **Integration**.
3. Install **Hermes** and restart Home Assistant.

### Manual

Copy `custom_components/hermes` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Hermes** and choose a source.

**Tracking codes** — there is nothing to fill in: the hub is created immediately. Then add parcels via the integration's **Configure** dialog, the [`hermes.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking code is on your shipping confirmation email or the missed-delivery card. Only one tracking hub can exist.

**Hermes account** — enter your account username and password. Only the login tokens are stored, never the password; if Hermes stops accepting them you are asked for the password again. You can add more than one account, and an account can sit next to the tracking hub. An account has no tracked-parcel list — its parcels come from your account — so its **Configure** dialog offers settings only, and the `track_parcel` / `untrack_parcel` services only ever act on the tracking hub.

Parcels from a tracking code carry the sender when Hermes names one, and the expected delivery window Hermes forecasts — a time span on a delivery day, or the moment a parcel becomes collectable at a PaketShop. The receiver, the PaketShop's own name and address, the weight and the dimensions are not on this route, so those fields stay empty.

Parcels from an account carry the sender (the shop or person who sent it), the receiver's first name when Hermes provides it, and — for a parcel routed to a PaketShop — that shop's name and address as the pickup point. Hermes does not report a weight, dimensions or an expected delivery window for account parcels, so those fields stay empty.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes (tracking hub only). Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

## Dynamic polling

Instead of polling Hermes at the same rate around the clock, the integration
adjusts its own cadence to what your tracked parcels are actually doing:

- **Quiet hours** — no polling between 00:00–06:00 local time, aside from one
  catch-up check at each end of that window (around midnight and around 6
  AM).
- **Hot (every 15 minutes)** — as soon as a tracked parcel is
  `out_for_delivery`, starting an hour before its expected delivery time (or
  immediately if no time is known).
- **Mid (every 45 minutes)** — any other in-progress parcel.
- **Fully stopped** — nothing is tracked, or every tracked parcel has been
  delivered. Adding a parcel back (via the options dialog, the
  `hermes.track_parcel` service, or a dashboard button) resumes polling
  immediately.
- A small, fixed per-hub offset is added on top, so not every Hermes hub out
  there polls at exactly the same second.

This is not user-configurable — it is the only polling behaviour for tracking
codes. A Hermes account polls its whole inbox in one request every 45 minutes
and never suspends.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Hermes → ⋮ → Delete**. Nothing is stored on Hermes's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.hermes_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.hermes_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.hermes_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.hermes_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.hermes_last_successful_update` | Diagnostic: when Hermes was last polled successfully |

Entities of an account entry are named after the account, e.g. `sensor.hermes_<username>_incoming_parcels`.

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

A **Deliveries** calendar entity is also created, showing expected delivery
windows for active parcels — read-only, no extra API calls.

A **Refresh** button entity forces an immediate poll, without waiting for the
next scheduled poll.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | Announced / received by Hermes |
| `in_transit` | In the sorting network |
| `out_for_delivery` | With the courier today |
| `at_pickup_point` | Waiting for you at a pickup location |
| `delivered` | Delivered |
| `returning` | Going back to the sender |
| `problem` | Hermes reports an exception |
| `unknown` | Not yet scanned, or a status we have not mapped yet |

The carrier's own human-readable text is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Hermes device):

| Event | When |
|---|---|
| `hermes_parcel_registered` | A new parcel appears in the active list |
| `hermes_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `hermes_parcel_delivered` | A parcel is delivered |
| `hermes_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `hermes.track_parcel` | `tracking_code` | Start tracking a parcel |
| `hermes.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.hermes: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Hermes has not scanned it yet (their API answers `404` until the first scan), or the number is wrong. It will pick up automatically once scanned.
- **Account: "Hermes refused this request"** — the Hermes gateway rejected the request before it checked your login, so signing in again will not help. The cause is not knowable from the response alone (a rotated app key, a network/region block and a transient refusal all look identical), so enable [debug logging](#debugging) and [open an issue](https://github.com/ha-parcel-integrations/ha-hermes/issues/new) with the logged gateway response if it persists.
- **Account: a parcel shows `unknown` with no details** — Hermes lists some old parcels without any status information.
- **A status logs "Unrecognised Hermes status" or "Unrecognised Hermes account status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-hermes/issues/new) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://ha-parcel-integrations.github.io/) for the current list of supported carriers.

## Disclaimer

This is an independent, community-built project. It is not affiliated with, endorsed by, sponsored by, or supported by Hermes, Home Assistant, or any other third party referenced in this project. Please don't contact Hermes for support with this integration.

All third-party trademarks, trade names, product names, logos, and other brand assets are the property of their respective owners. References to them are solely to identify the relevant carrier or service and do not imply affiliation, sponsorship, or endorsement. Nothing in this project grants or implies any licence or right to use third-party brand assets.

This integration may rely on public, unofficial, or undocumented carrier interfaces, accessed with your own account or API key where required. These may change or be withdrawn without notice and may be subject to Hermes' terms. Data is sent only to Hermes' own services or those of its group; this project operates no servers of its own. You are responsible for ensuring that your use complies with applicable law and those terms. Use is at your own risk; see the [licence](LICENSE) for warranty limitations.

This integration uses the same public tracking endpoint as the Hermes consumer website.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
