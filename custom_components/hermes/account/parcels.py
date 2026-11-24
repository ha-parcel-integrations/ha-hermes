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
from ..contents import clean_contents
from ..status import ACCOUNT_STATUS_MAP, NEW_ISSUE_URL
from ..tracking.parcels import is_pickup, parse_iso, to_iso_timestamp, tracking_url

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


_BACK_AT_SENDER = frozenset(
    {
        "RETOURE_AUSGELIEFERT_BEIM_ATG",
        "RETOURE_AUSGELIEFERT_BEIM_ATG_NACH_SCHADEN",
    }
)


def _dict(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a dict, else an empty one."""
    return value if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: Any) -> str | None:
    """Return a non-empty trimmed string, else ``None``."""
    return value.strip() or None if isinstance(value, str) else None


def _pickup_point(address: dict[str, Any]) -> str | None:
    """Return the PaketShop as "name, street, zip city", else ``None``.

    Hermes reuses one ``address`` block for every destination and distinguishes
    them by ``addressType``: a home delivery carries only a first name, while a
    shop carries the whole shop record with its name in ``lastName``. Anything
    other than ``PARCELSHOP`` therefore has no pickup point, and reading the
    block unconditionally would publish the receiver's own name as one.
    """
    if address.get("addressType") != "PARCELSHOP":
        return None
    return _text(address.get("lastName"))


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
            "raw_status": event.get("statusHistoryText")
            or event.get("statusHistoryShortText")
            or code,
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

    # Hermes' own boolean, never inferred from the status; it wins over a shop
    # status because a collected parcel is delivered.
    mapped_status = status
    flag = _dict(raw.get("metaInformation")).get("delivered")
    if flag is True and status is not ParcelStatus.RETURNING:
        status = ParcelStatus.DELIVERED
    elif flag is False and status is ParcelStatus.DELIVERED:
        status = ParcelStatus.IN_TRANSIT
    # A return delivered back to the sender is finished but stays ``returning``.
    delivered = status is ParcelStatus.DELIVERED or (
        status is ParcelStatus.RETURNING and code in _BACK_AT_SENDER
    )
    address = _dict(raw.get("address"))
    first_name = address.get("firstName")
    pickup = is_pickup(
        address.get("addressType") == "PARCELSHOP",
        mapped_status,
        (
            ACCOUNT_STATUS_MAP.get(event.get("status") or "")
            for event in _dict_list(raw.get("parcelHistory"))
        ),
    )

    return {
        "carrier": "Hermes",
        "barcode": barcode,
        "sender": _text(_dict(raw.get("atg")).get("companyName")),
        "receiver": first_name if isinstance(first_name, str) and first_name else None,
        "contents": clean_contents(raw.get("description")),
        "status": status,
        "raw_status": _dict(status_block.get("text")).get("longText") or code,
        "delivered": delivered,
        "delivered_at": (
            to_iso_timestamp(status_block.get("deliveryTime")) if delivered else None
        ),
        "planned_from": None,
        "planned_to": None,
        "pickup": pickup,
        "pickup_point": _pickup_point(address) if pickup else None,
        "url": tracking_url(barcode),
        "weight": None,
        "dimensions": None,
        "history": (
            _build_history(raw.get("parcelHistory")) if include_history else None
        ),
        "raw": raw,
    }
