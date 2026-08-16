"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

The two carrier-specific pieces are :data:`_STATUS_MAP` (Hermes ``parcelStatus``
→ canonical status) and :func:`normalize_parcel` (the Paket ``{barcode,
parcelProgress}`` payload → canonical shape). Everything else — the timestamp
parsing, the history builder, the sort contract, the delivered filter, the
one-shot warning for unmapped statuses — is suite-wide machinery and should be
left alone.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-hermes/issues/new"
    "?template=unrecognised_status.yml"
)

# Hermes ``parcelStatus`` (the stable English enum on each ``parcelProgress``
# event) → canonical ParcelStatus. Seeded from the values mapped in
# ``itsvic-dev/deliveries`` (HermesDeliveryService.kt) plus the pickup family
# from the app decompile; extend it as real parcels surface more. An unmapped
# value surfaces as ``unknown`` plus a one-shot warning that asks the user to
# report it — do not map the localised ``status`` / ``historyText`` here, only
# the stable ``parcelStatus`` code.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "ANNOUNCED": ParcelStatus.REGISTERED,
    "PARCELSHOP_DROP_OFF": ParcelStatus.REGISTERED,
    "TAKEN_OVER_BY_HERMES": ParcelStatus.IN_TRANSIT,
    "PARCELSHOP_COLLECTED_BY_DRIVER": ParcelStatus.IN_TRANSIT,
    "SORTED": ParcelStatus.IN_TRANSIT,
    "ARRIVED_IN_DESTINATION_REGION": ParcelStatus.IN_TRANSIT,
    "DELIVERY_TOUR_STARTED": ParcelStatus.OUT_FOR_DELIVERY,
    "DELIVERED_HOMEDELIVERY": ParcelStatus.DELIVERED,
    "DELIVERED_PARCELSHOP": ParcelStatus.DELIVERED,
    "DELIVERED_MAILBOX": ParcelStatus.DELIVERED,
    "DELIVERED_DROPOFF": ParcelStatus.DELIVERED,
    "PARCELSHOP_ITEMS_FOR_COLLECTION": ParcelStatus.AT_PICKUP_POINT,
    "READY_FOR_COLLECTION": ParcelStatus.AT_PICKUP_POINT,
    "RETURN_DELIVERED_TO_SENDER": ParcelStatus.RETURNING,
    "RETURN": ParcelStatus.RETURNING,
    "NOT_DELIVERABLE": ParcelStatus.PROBLEM,
    "UNKNOWN_WHEREABOUTS": ParcelStatus.PROBLEM,
}

# ``EDL_BOOKED_DROPOFF`` ("Wunschablageort gebucht") is deliberately left
# unmapped: it is a delivery-preference booking, not a location movement, and
# real evidence (ha-hermes#1) shows it firing *before* Hermes even collects
# the parcel — mapping it to any single ParcelStatus risks regressing the
# status backwards on a parcel where the same event fires later in transit.
# It falls through to the unmapped-code warning like any other new code.

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()

# The confirmed typed model is ``{barcode, parcelProgress, parcelAttributes}``;
# a real 200 (ha-hermes#1) also carries ``ablt``, ``address``, ``atg``,
# ``bookedEdl``, ``forecast``, ``latestRelatedBarcode``, ``livetrackingOptions``,
# ``n1ParcelShopEligible``, ``viewParameters`` — none yet confirmed to carry
# sender/recipient/eta/parcelShop (open: issue #3). Any field beyond the known
# set logs once — keys only, never values (they can be personal) — so a
# tester can confirm what we should wire up next. See NEW_ISSUE_URL.
_KNOWN_PAYLOAD_KEYS = {"barcode", "parcelProgress", "parcelAttributes"}
_payload_shape_logged = False


def _note_payload_shape(raw: dict) -> None:
    """One-shot: report unconfirmed top-level fields so a tester can map them."""
    global _payload_shape_logged
    if _payload_shape_logged:
        return
    extra = sorted(set(raw) - _KNOWN_PAYLOAD_KEYS)
    if not extra:
        return
    _payload_shape_logged = True
    _LOGGER.warning(
        "Hermes payload carries fields we have not confirmed against a real "
        "parcel yet: %s. Please help us map them — a diagnostics file is ideal: %s",
        extra,
        NEW_ISSUE_URL,
    )


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Hermes status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a carrier status code to a canonical :class:`ParcelStatus`.

    ``None`` (a not-yet-scanned parcel) reports ``unknown`` silently; an
    unrecognised code reports ``unknown`` with a one-shot warning.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return ParcelStatus.UNKNOWN


def map_event_status(code: str | None) -> ParcelStatus | None:
    """Map a history entry's status code to a canonical status, or ``None``.

    Unmapped codes keep ``status: null`` on the history entry (rather than
    ``unknown``, so a consumer can tell "no mapping" from "mapped to unknown")
    and warn once, reusing the parcel-status one-shot set.
    """
    if not code:
        return None
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def format_dimensions(
    length: float | None, width: float | None, height: float | None
) -> dict[str, Any] | None:
    """Return the canonical ``dimensions`` dict, or ``None`` when incomplete.

    Units contract: **centimetres**, with ``text`` pre-formatted as
    ``"L x W x H cm"`` (integer values, lowercase ``x``) so dashboards can show
    a dimension without doing their own formatting. Convert before calling if
    the carrier reports millimetres or inches.
    """
    if length is None or width is None or height is None:
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{int(length)} x {int(width)} x {int(height)} cm",
    }


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from the carrier's event list.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. ``raw_status`` is the carrier's own text
    (Hermes' localised ``historyText``), falling back to the ``parcelStatus``
    code when there is none. Sorted oldest → newest and capped to the most
    recent ``max_events``.

    ``events`` is Hermes' ``parcelProgress`` list — each entry
    ``{timestamp, status, parcelStatus, historyText}``.
    """
    parseable: list[tuple[datetime, dict]] = []
    unparseable: list[dict] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        timestamp = to_iso_timestamp(event.get("timestamp"))
        if not timestamp:
            continue
        entry = {
            "timestamp": timestamp,
            "status": map_event_status(event.get("parcelStatus")),
            "raw_status": event.get("historyText") or event.get("parcelStatus"),
        }
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in parseable] + unparseable
    return ordered[-max_events:]


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**: every carrier in the
    suite returns exactly these, in this order, and the aggregator and
    cross-carrier dashboards depend on it. A key is ``None`` when Hermes does not
    expose it — never omitted.

    Invariants:

    * ``status`` is canonical, ``raw_status`` is the carrier's own text —
      the latest event's ``historyText`` (localised), not its ``status``
      field, which is a generic outcome bucket (``HAPPY``/``FINISHED``, seen
      on every event regardless of what happened) rather than display text.
    * A delivered parcel has ``delivered_at`` set and ``planned_from`` /
      ``planned_to`` cleared — the ETA is meaningless once it has arrived.
    * ``delivered``/``delivered_at`` also fall back to
      ``parcelAttributes.delivered``/``deliveredTimestamp`` when the latest
      ``parcelStatus`` isn't one we map to :attr:`ParcelStatus.DELIVERED` yet —
      confirmed real (ha-hermes#1: a real parcel's terminal ``DELIVERED_DROPOFF``
      went unmapped for a release, and ``delivered`` stayed ``False`` the whole
      time). This keeps ``delivered`` correct even while ``status`` is
      ``unknown`` for a status we haven't mapped.
    * ``planned_to`` is ``None`` for a point estimate; only fill it when the
      carrier genuinely reports a *window*.
    * ``weight`` is kilograms, ``dimensions`` centimetres (see
      :func:`format_dimensions`).
    * ``history`` is ``None`` when the option is off — the key still exists.

    Hermes ``raw`` is ``{barcode, parcelProgress:[...]}`` (newest event first).
    The current status is the latest event's ``parcelStatus``.
    """
    _note_payload_shape(raw)
    tracking_code = raw.get("barcode")
    progress = raw.get("parcelProgress") or []
    latest = progress[0] if progress and isinstance(progress[0], dict) else {}

    status_code = latest.get("parcelStatus")
    status = map_parcel_status(status_code)

    attributes = raw.get("parcelAttributes")
    attributes = attributes if isinstance(attributes, dict) else {}
    delivered = status is ParcelStatus.DELIVERED or bool(attributes.get("delivered"))

    # ETA: the confirmed typed model (barcode + parcelProgress) carries no ETA,
    # but the myhermes.de widget reads an ``eta`` / ``deliveryForecast`` field a
    # real 200 may include. Read it defensively — only a scalar (ISO string /
    # epoch) is used; anything else (or absent) yields ``None``. Confirm the
    # exact field/shape against a real parcel (see TODO.md).
    eta = raw.get("eta") or raw.get("deliveryForecast")
    planned_from = to_iso_timestamp(eta) if isinstance(eta, (str, int, float)) else None

    # sender / receiver / pickup-point are likewise not in the confirmed model;
    # kept ``None`` for parity until a real 200 confirms them. ``weight`` /
    # ``dimensions`` are never exposed by Hermes.
    return {
        "carrier": "Hermes",
        "barcode": tracking_code,
        "sender": None,
        "receiver": None,
        "status": status,
        "raw_status": latest.get("historyText") or status_code,
        "delivered": delivered,
        "delivered_at": (
            to_iso_timestamp(latest.get("timestamp"))
            if status is ParcelStatus.DELIVERED
            else to_iso_timestamp(attributes.get("deliveredTimestamp"))
            if delivered
            else None
        ),
        "planned_from": None if delivered else planned_from,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": None,
        "url": tracking_url(tracking_code),
        "weight": None,
        "dimensions": None,
        "history": build_history(progress) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(
        CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
    )
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
