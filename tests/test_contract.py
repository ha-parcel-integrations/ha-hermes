"""The parcel contract's checks, run over every source's normalised samples."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.hermes.account.parcels import normalize_account_parcel
from custom_components.hermes.const import ParcelStatus
from custom_components.hermes.tracking.parcels import (
    is_pickup,
    normalize_parcel,
    planned_for_status,
    planned_window,
)

from .account.payloads import delivered_shipment, in_flight_shipment, thin_shipment
from .tracking.payloads import active_sample, delivered_sample, pickup_sample

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "contents",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]

_BERLIN = ZoneInfo("Europe/Berlin")
_SHOP = {"addressType": "PARCELSHOP", "lastName": "Example Shop", "street": "Main 1"}


def _forecast(**forecast):
    sample = active_sample()
    sample["forecast"] = forecast
    return lambda: normalize_parcel(sample)


def _shop(**meta):
    shipment = in_flight_shipment("ZUSTELLTOUR")
    shipment["address"] = dict(_SHOP)
    shipment["metaInformation"] = meta
    return shipment


SAMPLES = {
    "tracked_active": lambda: normalize_parcel(active_sample()),
    "tracked_at_pickup": lambda: normalize_parcel(pickup_sample()),
    "tracked_delivered": lambda: normalize_parcel(delivered_sample()),
    "tracked_window": _forecast(
        deliveryTimeFromUTC="2099-05-22T11:00:00Z",
        deliveryTimeToUTC="2099-05-22T13:00:00Z",
    ),
    "tracked_moment": _forecast(deliveryTimeFromUTC="2099-05-22T11:00:00Z"),
    "account_in_flight": lambda: normalize_account_parcel(in_flight_shipment()),
    "account_delivered": lambda: normalize_account_parcel(delivered_shipment()),
    "account_thin": lambda: normalize_account_parcel(thin_shipment()),
    "account_shop_delivered": lambda: normalize_account_parcel(
        {**delivered_shipment(), "address": dict(_SHOP)}
    ),
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return SAMPLES[request.param]()


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert datetime.fromisoformat(parcel["planned_to"]) > datetime.fromisoformat(
            parcel["planned_from"]
        )


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_a_collected_shop_parcel_stays_pickup_and_keeps_the_shop_name():
    parcel = SAMPLES["account_shop_delivered"]()
    assert parcel["delivered"] is True
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example Shop"


def test_an_explicit_delivered_flag_wins_over_a_shop_status():
    parcel = normalize_account_parcel(
        {**in_flight_shipment(), "address": dict(_SHOP)}
        | {
            "status": {"parcelStatus": "ZUGESTELLT_PAKETSHOP"},
            "metaInformation": {"delivered": True},
        }
    )
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["pickup_point"] == "Example Shop"


def _tracked_return(code, delivered_flag):
    sample = active_sample()
    sample["parcelAttributes"] = {"delivered": delivered_flag}
    sample["parcelProgress"][0]["parcelStatus"] = code
    return normalize_parcel(sample)


def _account_return(code, delivered_flag):
    shipment = in_flight_shipment()
    shipment["status"] = {**shipment["status"], "parcelStatus": code}
    shipment["metaInformation"] = {"delivered": delivered_flag}
    return normalize_account_parcel(shipment)


def test_a_return_back_at_the_sender_is_finished_but_stays_returning():
    for parcel in (
        _tracked_return("RETURN_DELIVERED_TO_SENDER", True),
        _account_return("RETOURE_AUSGELIEFERT_BEIM_ATG", True),
    ):
        assert parcel["status"] is ParcelStatus.RETURNING
        assert parcel["delivered"] is True
        assert parcel["planned_from"] is None


def test_the_delivered_flag_does_not_turn_a_return_into_a_delivery():
    for parcel in (
        _tracked_return("RETURN_TO_SENDER", True),
        _account_return("RETOURE_AUSLIEFERUNG_ZUM_ATG", True),
    ):
        assert parcel["status"] is ParcelStatus.RETURNING
        assert parcel["delivered"] is False


def test_a_window_keeps_both_ends():
    parcel = SAMPLES["tracked_window"]()
    assert parcel["planned_from"] == "2099-05-22T11:00:00Z"
    assert parcel["planned_to"] == "2099-05-22T13:00:00Z"


def test_a_moment_ends_at_the_end_of_the_local_day():
    parcel = SAMPLES["tracked_moment"]()
    assert parcel["planned_to"] == "2099-05-22T23:59:59+02:00"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            "2026-04-29T13:00:00+02:00",
            "2026-04-29T15:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T15:00:00+02:00"),
        ),
        (
            "2026-04-29T13:00:00+02:00",
            None,
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29T13:00:00+02:00",
            "2026-04-29T13:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29T13:00:00",
            None,
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29",
            None,
            ("2026-04-29T00:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            date(2026, 4, 29),
            date(2026, 4, 29),
            ("2026-04-29T00:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            "2026-04-29",
            "2026-05-01",
            ("2026-04-29T00:00:00+02:00", "2026-05-01T23:59:59+02:00"),
        ),
        (
            "2026-04-29T15:00:00+02:00",
            "2026-04-29T13:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T15:00:00+02:00"),
        ),
        (
            None,
            "2026-04-29T13:00:00+02:00",
            ("2026-04-29T13:00:00+02:00", "2026-04-29T23:59:59+02:00"),
        ),
        (
            datetime(2026, 4, 29, 13, 0),
            datetime(2026, 4, 29, 15, 0),
            ("2026-04-29T13:00:00+02:00", "2026-04-29T15:00:00+02:00"),
        ),
        (None, None, (None, None)),
        ("garbage", None, (None, None)),
        (12, 13, (None, None)),
    ],
)
def test_planned_window_shapes(start, end, expected):
    assert planned_window(start, end, zone=_BERLIN) == expected


@pytest.mark.parametrize(
    "status",
    [ParcelStatus.AT_PICKUP_POINT, ParcelStatus.RETURNING, ParcelStatus.DELIVERED],
)
def test_planned_for_status_empties_the_window(status):
    assert planned_for_status(status, "a", "b") == (None, None)


def test_planned_for_status_keeps_the_window_otherwise():
    for status in (
        ParcelStatus.REGISTERED,
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.OUT_FOR_DELIVERY,
        ParcelStatus.PROBLEM,
        ParcelStatus.UNKNOWN,
    ):
        assert planned_for_status(status, "a", "b") == ("a", "b")


def test_is_pickup_sources():
    assert is_pickup(True, ParcelStatus.IN_TRANSIT) is True
    assert is_pickup(None, ParcelStatus.AT_PICKUP_POINT) is True
    assert is_pickup(None, ParcelStatus.DELIVERED, [None, ParcelStatus.AT_PICKUP_POINT])
    assert is_pickup(False, ParcelStatus.IN_TRANSIT, [ParcelStatus.IN_TRANSIT]) is False
    assert is_pickup(None, ParcelStatus.DELIVERED) is False
