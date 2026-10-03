"""Normalisation for Hermes account shipments.

The account route shapes its own payload: the status vocabulary is German
(``ACCOUNT_STATUS_MAP``), ``parcelHistory`` is oldest-first, and a thin
``IN_UNKNOWN`` element carries no ``status`` block at all. Fields the response
does not carry stay ``None`` — never guessed.
"""
from __future__ import annotations

import logging
from typing import Any

from ..const import HISTORY_MAX_EVENTS, ParcelStatus
from ..status import ACCOUNT_STATUS_MAP, NEW_ISSUE_URL
from ..tracking.parcels import parse_iso, to_iso_timestamp, tracking_url

_LOGGER = logging.getLogger(__name__)

# Status codes already warned about, so each unmapped one is logged once per
# HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped account status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Hermes account status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def _dict(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a dict, else an empty one."""
    return value if isinstance(value, dict) else {}


def _build_history(events: Any) -> list[dict]:
    """Return canonical ``{timestamp, status, raw_status}`` entries, oldest first.

    Sorted by timestamp rather than trusting the array order, and capped to the
    most recent ``HISTORY_MAX_EVENTS``. A code outside the map keeps
    ``status: None`` so a consumer can tell "no mapping" from "unknown".
    """
    parseable = []
    unparseable = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        timestamp = to_iso_timestamp(event.get("timestamp"))
        if not timestamp:
            continue
        code = event.get("status")
        entry = {
            "timestamp": timestamp,
            "status": ACCOUNT_STATUS_MAP.get(code) if isinstance(code, str) else None,
            "raw_status": event.get("statusHistoryShortText") or code,
        }
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in parseable] + unparseable
    return ordered[-HISTORY_MAX_EVENTS:]


def normalize_account_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return the canonical parcel shape for one ``GET /shipments`` element.

    * The current status is ``status.parcelStatus`` — never the first or last
      ``parcelHistory`` entry.
    * ``delivered`` is ``metaInformation.delivered``, a real boolean, and is not
      inferred from the status.
    * ``address`` is the receiver. The response has no sender;
      ``atg.companyName`` is the delivery partner, so ``sender`` stays ``None``.
    * ``planned_from``, ``planned_to``, ``pickup_point``, ``weight`` and
      ``dimensions`` are always ``None``: nothing in the list response proves
      them.
    * A thin element has no ``status`` block; it reports ``unknown``.
    """
    barcode = raw.get("barcode")
    barcode = barcode if isinstance(barcode, str) and barcode else None

    status_block = _dict(raw.get("status"))
    code = status_block.get("parcelStatus")
    code = code if isinstance(code, str) and code else None
    if code is None:
        status = ParcelStatus.UNKNOWN
    elif code in ACCOUNT_STATUS_MAP:
        status = ACCOUNT_STATUS_MAP[code]
    else:
        status = ParcelStatus.UNKNOWN
        _warn_unmapped_status(code)

    delivered = _dict(raw.get("metaInformation")).get("delivered") is True
    first_name = _dict(raw.get("address")).get("firstName")

    return {
        "carrier": "Hermes",
        "barcode": barcode,
        "sender": None,
        "receiver": first_name if isinstance(first_name, str) and first_name else None,
        "status": status,
        "raw_status": _dict(status_block.get("text")).get("longText") or code,
        "delivered": delivered,
        "delivered_at": (
            to_iso_timestamp(status_block.get("deliveryTime")) if delivered else None
        ),
        "planned_from": None,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": None,
        "url": tracking_url(barcode),
        "weight": None,
        "dimensions": None,
        "history": (
            _build_history(raw.get("parcelHistory")) if include_history else None
        ),
        "raw": raw,
    }
