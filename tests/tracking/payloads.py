"""Sample Hermes Paket API payloads shared by the test modules.

Modelled on the confirmed `api.my-deliveries.de/tnt/v2/shipments/search/{id}`
shape (from `itsvic-dev/deliveries`, the myhermes.de widget, and — for
`dropoff_delivered_sample` — a real redacted response, ha-hermes#1): a
per-parcel object is ``{barcode, parcelProgress:[...]}`` with the newest event
first, plus a ``parcelAttributes`` block confirmed on that real parcel. Kept
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


def dropoff_delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """The real payload from ha-parcel-integrations/ha-hermes#1 (redacted).

    A safe drop-off delivery. Two things a modelled fixture had never
    exercised before this real parcel surfaced them: the latest event's
    ``status`` is the generic outcome bucket ``FINISHED`` — distinct from its
    ``historyText`` — and the top-level payload carries a ``parcelAttributes``
    block with its own ``delivered``/``deliveredTimestamp``.
    """
    return {
        "barcode": code,
        "parcelAttributes": {
            "delivered": True,
            "deliveredTimestamp": "2026-08-10T08:16:21.025Z",
        },
        "parcelProgress": [
            event(
                "DELIVERED_DROPOFF",
                "2026-08-10T08:16:21.025Z",
                "Die Sendung wurde an einem Ablageort hinterlegt.",
                status="FINISHED",
            ),
            event(
                "DELIVERY_TOUR_STARTED",
                "2026-08-10T06:59:25Z",
                "Die Sendung wurde ins Zustellfahrzeug geladen.",
                status="HAPPY",
            ),
            event(
                "ARRIVED_IN_DESTINATION_REGION",
                "2026-08-10T02:20:50Z",
                "Die Sendung ist in der Zielregion angekommen.",
                status="HAPPY",
            ),
            event(
                "SORTED",
                "2026-08-08T15:36:02Z",
                "Die Sendung wurde für den Weiterversand vorbereitet.",
                status="HAPPY",
            ),
            event(
                "PARCELSHOP_COLLECTED_BY_DRIVER",
                "2026-08-08T09:27:41Z",
                "Die Sendung wurde von Hermes im PaketShop abgeholt.",
                status="HAPPY",
            ),
            event(
                "EDL_BOOKED_DROPOFF",
                "2026-08-07T16:00:12Z",
                "Für die Sendung wurde ein WunschAblageort gebucht.",
                status="HAPPY",
            ),
            event(
                "PARCELSHOP_DROP_OFF",
                "2026-08-07T14:29:35Z",
                "Die Sendung wurde vom Absender im PaketShop abgegeben.",
                status="HAPPY",
            ),
            event(
                "ANNOUNCED",
                "2026-08-07T10:57:11Z",
                "Die Sendung wurde Hermes elektronisch angekündigt.",
                status="HAPPY",
            ),
        ],
    }
