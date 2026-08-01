# Hermes Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-hermes.svg)](https://github.com/ha-parcel-integrations/ha-hermes/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Hermes](https://www.myhermes.de) (Germany, "Hermes Paket") parcels. No account is needed — you enter the 14-digit tracking number yourself, just like on the myhermes.de tracking page.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

> ### ⚠️ Early release — well-evidenced, not yet confirmed
>
> The endpoint is live and keyless, and unknown or badly-formatted numbers are
> handled correctly. The success payload and status vocabulary come from three
> independent sources that agree, but have **not yet been confirmed against a
> real parcel** here. Any status we do not map reports **`unknown`** (never a
> wrong status) and logs a one-shot warning with a ready-made issue link —
> please [report it](https://github.com/ha-parcel-integrations/ha-hermes/issues/new?template=unrecognised_status.yml)
> so the mapping can be completed.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
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
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), the carrier's own status text and a tracking deep-link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the expected delivery windows
- `hermes.track_parcel` / `hermes.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.7 or newer
- A Hermes parcel and its tracking code (from the shipping
  confirmation email or the missed-delivery card) — no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-hermes` as an **Integration**.
3. Install **Hermes** and restart Home Assistant.

### Manual

Copy `custom_components/hermes` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Hermes**. There is nothing to fill in: the hub is created immediately (Hermes tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`hermes.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking code is on your shipping confirmation email or the missed-delivery card.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |
| Polling | Refresh every | 30 min | How often Hermes is checked. Slower is gentler on their API. |

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

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

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
- **A status logs "Unrecognised Hermes status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-hermes/issues/new) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as the Hermes consumer website. It is not affiliated with, endorsed by, or supported by Hermes. Be gentle with the polling interval.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
