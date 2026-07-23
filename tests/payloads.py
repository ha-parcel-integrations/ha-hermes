"""Sample Hermes Paket API payloads shared by the test modules.

Modelled on the confirmed `api.my-deliveries.de/tnt/v2/shipments/search/{id}`
shape (from `itsvic-dev/deliveries` and the myhermes.de widget): a per-parcel
object is ``{barcode, parcelProgress:[...]}`` with the newest event first. Kept
in one module so that when a real (redacted) response confirms extra fields,
there is exactly one place to extend.
"""
from __future__ import annotations

ACTIVE_CODE = "12345678909999"
DELIVERED_CODE = "12345678901234"


def event(parcel_status: str, timestamp, history_text: str, status: str | None = None) -> dict:
    """One entry of Hermes' ``parcelProgress`` timeline.

    ``parcelStatus`` is the stable English enum (what we map); ``status`` /
    ``historyText`` are the localised display fields (``status`` defaults to the
    history text).
    """
    return {
        "timestamp": timestamp,
        "status": history_text if status is None else status,
        "parcelStatus": parcel_status,
        "historyText": history_text,
    }


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """A representative tracking response for a delivered parcel."""
    return {
        "barcode": code,
        "parcelProgress": [
            event("DELIVERED_HOMEDELIVERY", "2026-04-29T13:12:42Z", "Delivered to the recipient"),
            event("DELIVERY_TOUR_STARTED", "2026-04-29T08:46:00Z", "Out for delivery"),
            event("SORTED", "2026-04-28T15:52:17Z", "At the sorting facility"),
            event("ANNOUNCED", "2026-04-27T23:03:58Z", "Shipment announced"),
        ],
    }


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """An out-for-delivery parcel (latest event = tour started)."""
    return {
        "barcode": code,
        "parcelProgress": delivered_sample(code)["parcelProgress"][1:],
    }


def pickup_sample(code: str = ACTIVE_CODE) -> dict:
    """A parcel waiting at a ParcelShop for collection."""
    sample = active_sample(code)
    sample["parcelProgress"] = [
        event("PARCELSHOP_ITEMS_FOR_COLLECTION", "2026-04-29T09:10:00Z", "Ready for collection"),
        *sample["parcelProgress"],
    ]
    return sample
