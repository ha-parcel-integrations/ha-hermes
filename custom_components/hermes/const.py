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

# Which optional contract fields each source's API actually populates — feeds
# the comparison table on the docs site. Keep in lockstep with the matching
# normaliser (tracking/parcels.py, account/parcels.py): everything not listed
# here comes back as a literal None there. Neither source exposes weight or
# dimensions. The keyless route reads its delivery window from the widget's own
# `forecast` block and has no pickup point; the account route names the
# PaketShop a parcel went to, but has never been seen with a populated ETA, so
# it claims no delivery window.
CAPABILITIES_BY_VARIANT = {
    "Tracking": frozenset({"delivery_window", "url", "history"}),
    "Account": frozenset({"pickup_point", "url", "history"}),
}

# Fields not confirmed yet — the docs site shows them as "awaiting data".
# Move a field into the declaration above once a real parcel shows it.
PENDING_CAPABILITIES_BY_VARIANT = {
    "Account": frozenset({"delivery_window"}),
}
CAPABILITIES = CAPABILITIES_BY_VARIANT["Tracking"]

# Hermes Germany's consumer **Paket** track-and-trace endpoint. This is the same
# API the myhermes.de tracking widget (`tnt-bundle-v2.js`) calls, cross-checked
# against two other clients — `itsvic-dev/deliveries` (Android, MIT) and
# `dbalan/hermes` (HA).
#
# * **Keyless, code-based.** No API key, no Bearer, no auth header — the parcel
#   number alone (the Dragonfly model). Probed 2026-07-23 with no key and no
#   cookie: a 14-digit number 404s (not found), a 12-digit one 400s (bad
#   format). No bot wall on this path. **No postcode required.**
# * **Response is a JSON array** of shipments; we track one code, so element 0
#   is the parcel. `api.py` returns `payload[0]`, or `None` when the array is
#   empty / the number is unknown (404) or malformed (400) — all normal states.
# * **Per-parcel shape**, confirmed on a real 200 (ha-hermes#1, 2026-08):
#   `{"barcode": str, "parcelAttributes": {"delivered": bool,
#   "deliveredTimestamp": iso, ...}, "parcelProgress": [{"timestamp": iso|null,
#   "status": str, "parcelStatus": str, "historyText": str|null}, ...], ...}`,
#   `parcelProgress` newest event first. Map the **stable English
#   `parcelStatus`** — `status` is *not* the localised display text, it is a
#   generic outcome bucket (`HAPPY` / `FINISHED`, unrelated to which event
#   fired); the actual localised text is `historyText`. `parcelAttributes`
#   is a resilient secondary signal for `delivered`. Real 200s also carry
#   `ablt`, `address`, `atg`, `bookedEdl`, `forecast`, `latestRelatedBarcode`,
#   `livetrackingOptions`, `n1ParcelShopEligible`, `viewParameters` — none
#   confirmed to carry sender/recipient/eta/parcelShop yet (open: issue #3).
# * **Rate limits / throttling:** none observed — dynamic status-driven polling
#   (const.py's HOT_/MID_INTERVAL_MINUTES) applies unconditionally, same as
#   the other keyless carriers.
#
# NB: this is Hermes **Paket** (mass-market). `myhes.de` (the niche
# Einrichtungs-Service / 2-man furniture arm) is deliberately NOT used. Also a
# separate company from Evri, the former Hermes UK — do not assume a shared
# endpoint.
TRACKING_API_URL = "https://api.my-deliveries.de/tnt/v2/shipments/search/{tracking_code}"

# Human-facing deep link on each parcel's ``url`` field. The consumer tracking
# page is a client-side SPA, so the exact deep-link shape is UNVERIFIED (open:
# issue #6); this is the search page with the code appended and may need
# adjusting once we can watch a real lookup.
TRACKING_URL = "https://www.myhermes.de/empfangen/sendungsverfolgung/#{tracking_code}"

# Which source an entry reads from. Every read defaults to the tracking source:
# entries created before the account source existed carry no such key, and that
# default is the whole migration.
CONF_SOURCE = "source"
SOURCE_TRACKING = "tracking"
SOURCE_ACCOUNT = "account"

# Account source. The login identifier is the account *username*, not an email
# address. Only the token pair is persisted; the password never is.
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

# Transport values for the account route. Never user credentials: do not
# expose them in the UI, diagnostics, logs or fixtures. A rejected key is a
# compatibility failure, not a reason to ask every user to log in again.
ACCOUNT_API_URL = "https://mobile-app-api.a0930.prd.hc.de/api/v12"
ACCOUNT_APP_VERSION = "12.1.1 (2689)"
ACCOUNT_API_KEY = "acefe97f-89fc-4f4e-9543-fc6b90f68928"

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

# Dynamic, status-driven polling — unconditional, no user-facing interval
# option.
#
# Quiet window: no polling between these local hours except the two anchors
# below, for overnight / end-of-day catch-up.
QUIET_WINDOW_START_HOUR = 0
QUIET_WINDOW_END_HOUR = 6

# Cadence while polling is active (minutes). Hot = at least one tracked,
# not-yet-delivered parcel is out_for_delivery within HOT_LOOKAHEAD_HOURS of
# its planned_from (or has no planned_from at all); mid = anything else still
# in flight. This is a barcode-based coordinator (Section 2.1): when every
# tracked parcel is delivered, or nothing is tracked, polling stops entirely
# instead of falling to the mid tier — see coordinator.py's
# ``_hottest_tier_minutes``.
HOT_INTERVAL_MINUTES = 15
MID_INTERVAL_MINUTES = 45
HOT_LOOKAHEAD_HOURS = 1

# Small, stable per-install offset added to every computed interval so
# different installs don't all hit an anchor or tier boundary at the same
# second. Deterministic (hash of the config entry id), not random.
STAGGER_MINUTES = 7

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Keep it off by default even when — as here — the timeline arrives in
# the same response and costs no extra request: it is a large attribute, and on
# carriers that need a second call per parcel the cost is real.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
