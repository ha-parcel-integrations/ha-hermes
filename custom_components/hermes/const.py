"""Constants for the Hermes parcel tracker integration."""
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "hermes"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    **Do not extend or rename these members.** Every integration in the parcel
    suite publishes exactly this vocabulary on the ``status`` field of each
    normalised parcel, so cross-carrier automations and the aggregator can
    target ``status: out_for_delivery`` regardless of carrier. Listed in
    roughly the order a parcel moves through.
    """

    REGISTERED = "registered"               # Sender announced the parcel; not handed over yet
    IN_TRANSIT = "in_transit"               # In the carrier's network
    OUT_FOR_DELIVERY = "out_for_delivery"   # On a delivery vehicle today
    AT_PICKUP_POINT = "at_pickup_point"     # Ready to collect at a pickup location
    DELIVERED = "delivered"                 # Handed over
    RETURNING = "returning"                 # Failed delivery, going back to sender
    PROBLEM = "problem"                     # Carrier reports an exception/issue
    UNKNOWN = "unknown"                     # Raw status we have not mapped yet


PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# Every optional key the parcel contract defines. CAPABILITIES below must be a
# subset of this — it exists so a typo in CAPABILITIES fails a test instead of
# silently dropping this carrier off a table on the docs site.
KNOWN_CAPABILITIES = frozenset(
    {"weight", "dimensions", "delivery_window", "pickup_point", "url", "history"}
)

# Which optional contract fields this carrier's API actually populates — feeds
# the comparison table on the docs site. Keep in lockstep with
# normalize_parcel() in parcels.py: everything not listed here comes back as a
# literal None there. Hermes never exposes pickup_point, weight or dimensions;
# the delivery window is read defensively from an unconfirmed widget field.
CAPABILITIES = frozenset({"delivery_window", "url", "history"})

# Hermes Germany's consumer **Paket** track-and-trace endpoint. This is the same
# API the myhermes.de tracking widget (`tnt-bundle-v2.js`) calls, cross-checked
# against two other clients — `itsvic-dev/deliveries` (Android, MIT) and
# `dbalan/hermes` (HA) — see the private carrier-research repo `hermes-de.md`.
#
# * **Keyless, code-based.** No API key, no Bearer, no auth header — the parcel
#   number alone (the Dragonfly model). Probed 2026-07-23 with no key and no
#   cookie: a 14-digit number 404s (not found), a 12-digit one 400s (bad
#   format). No bot wall on this path (the *account* app API on a sibling host
#   is Api-Key-walled; this T&T path is not). **No postcode required.**
# * **Response is a JSON array** of shipments; we track one code, so element 0
#   is the parcel. `api.py` returns `payload[0]`, or `None` when the array is
#   empty / the number is unknown (404) or malformed (400) — all normal states.
# * **Per-parcel shape** (from the typed model in `itsvic-dev/deliveries`):
#   `{"barcode": str, "parcelProgress": [{"timestamp": iso|null, "status": str,
#   "parcelStatus": str, "historyText": str|null}, ...]}`, newest event first.
#   Map the **stable English `parcelStatus`** (not the localised `status` /
#   `historyText`). A real 200 may also carry sender/recipient/eta/parcelShop
#   fields the widget reads — still unconfirmed (see TODO.md), read defensively.
# * **Rate limits / throttling:** none observed — `--interval configurable` with
#   a gentle 30 min default, same as the other keyless carriers.
#
# NB: this is Hermes **Paket** (mass-market). Two other Hermes surfaces exist and
# are deliberately NOT used: `myhes.de` (the niche Einrichtungs-Service / 2-man
# furniture arm) and the account app API (Api-Key-walled). Also a separate
# company from Evri, the former Hermes UK — do not assume a shared endpoint.
TRACKING_API_URL = "https://api.my-deliveries.de/tnt/v2/shipments/search/{tracking_code}"

# Human-facing deep link on each parcel's ``url`` field. The consumer tracking
# page is a client-side SPA, so the exact deep-link shape is UNVERIFIED (see
# TODO.md); this is the search page with the code appended and may need
# adjusting once we can watch a real lookup.
TRACKING_URL = "https://www.myhermes.de/empfangen/sendungsverfolgung/#{tracking_code}"

# Tracked parcels live in the config entry options as a list of
# ``{tracking_code}`` dicts — this carrier has no account or parcel feed, so the
# user enters the codes themselves. Kept as dicts so future per-parcel fields
# slot in without an options migration.
CONF_PARCELS = "parcels"
CONF_TRACKING_CODE = "tracking_code"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Refresh interval (minutes) controls how often the coordinator polls the
# carrier. Default 30 min keeps the load on a consumer endpoint gentle; the
# minimum is 15 min for the same reason.
#
# Deliberate divergence from the HA Core rule that polling intervals are not
# user-configurable: that rule targets core integrations, and in a HACS parcel
# tracker a tunable cadence is a wanted feature. Generate with
# ``--interval fixed`` instead when the carrier throttles or soft-bans unusual
# traffic — that drops the option entirely and hard-codes the cadence, so users
# cannot dial it down to something that gets them blocked.
CONF_REFRESH_INTERVAL = "refresh_interval"
REFRESH_INTERVAL_OPTIONS = (15, 30, 60, 120, 240)
DEFAULT_REFRESH_INTERVAL = 30

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Keep it off by default even when — as here — the timeline arrives in
# the same response and costs no extra request: it is a large attribute, and on
# carriers that need a second call per parcel the cost is real.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
