"""Tests for normalising Hermes account shipments."""
import logging

from custom_components.hermes.account import parcels as account_parcels
from custom_components.hermes.account.parcels import normalize_account_parcel
from custom_components.hermes.const import ParcelStatus
from custom_components.hermes.status import (
    ACCOUNT_STATUS_MAP,
    TRACKING_STATUS_MAP,
)

from ..tracking.test_parcels import CANONICAL_KEYS
from .payloads import (
    BARCODE,
    THIN_BARCODE,
    delivered_shipment,
    in_flight_shipment,
    thin_shipment,
)


def test_publishes_exactly_the_canonical_keys_for_every_shape():
    for shipment in (delivered_shipment(), in_flight_shipment(), thin_shipment()):
        assert list(normalize_account_parcel(shipment)) == CANONICAL_KEYS


def test_delivered_shipment():
    parcel = normalize_account_parcel(delivered_shipment())
    assert parcel["carrier"] == "Hermes"
    assert parcel["barcode"] == BARCODE
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == (
        "Deine Sendung wurde an deiner Haustür zugestellt. Viel Spaß damit!"
    )
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-09-21T08:11:18.895Z"
    assert parcel["url"] == (
        f"https://www.myhermes.de/empfangen/sendungsverfolgung/#{BARCODE}"
    )
    assert parcel["pickup"] is False
    assert parcel["history"] is None  # opt-in, default off


def test_thin_in_unknown_element_normalises_to_unknown_without_raising():
    """The most likely crash: IN_UNKNOWN has no ``status`` block at all."""
    parcel = normalize_account_parcel(thin_shipment())
    assert parcel["barcode"] == THIN_BARCODE
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["raw_status"] is None
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None
    assert parcel["receiver"] is None
    assert parcel["history"] is None
    assert normalize_account_parcel(thin_shipment(), include_history=True)["history"] == []


def test_thin_element_does_not_warn_about_an_unmapped_status(caplog):
    with caplog.at_level(logging.WARNING):
        normalize_account_parcel(thin_shipment())
    assert "Unrecognised" not in caplog.text


def test_malformed_blocks_degrade_to_unknown():
    parcel = normalize_account_parcel(
        {"barcode": "", "status": "oops", "metaInformation": [], "address": 3}
    )
    assert parcel["barcode"] is None
    assert parcel["url"] is None
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["receiver"] is None


def test_status_comes_from_the_status_block_not_the_history():
    """History is oldest-first, so ``parcelHistory[0]`` is the *first* event."""
    shipment = in_flight_shipment("ZUSTELLTOUR")
    assert shipment["parcelHistory"][0]["status"] == "AVISE"
    assert normalize_account_parcel(shipment)["status"] == ParcelStatus.OUT_FOR_DELIVERY


def test_delivered_flag_is_not_inferred_from_the_status():
    shipment = delivered_shipment()
    shipment["metaInformation"]["delivered"] = False
    parcel = normalize_account_parcel(shipment)
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None

    shipment = in_flight_shipment()
    shipment["metaInformation"]["delivered"] = True
    assert normalize_account_parcel(shipment)["delivered"] is True


def test_history_is_oldest_first_and_maps_each_event():
    history = normalize_account_parcel(delivered_shipment(), include_history=True)[
        "history"
    ]
    assert [event["timestamp"] for event in history] == sorted(
        event["timestamp"] for event in history
    )
    assert history[0] == {
        "timestamp": "2026-09-14T01:34:39.176Z",
        "status": ParcelStatus.REGISTERED,
        "raw_status": "Sendung angekündigt",
    }
    assert history[-1]["status"] == ParcelStatus.DELIVERED
    assert len(history) == 7


def test_history_is_sorted_even_when_the_api_order_changes():
    shipment = delivered_shipment()
    shipment["parcelHistory"].reverse()
    history = normalize_account_parcel(shipment, include_history=True)["history"]
    assert history[0]["status"] == ParcelStatus.REGISTERED
    assert history[-1]["status"] == ParcelStatus.DELIVERED


def test_history_tolerates_junk_and_unmapped_events():
    shipment = delivered_shipment()
    shipment["parcelHistory"] = [
        "junk",
        {"status": "AVISE"},  # no timestamp
        {"status": "EDL_WUNSCHTERMIN", "timestamp": "2026-09-15T10:00:00Z"},
        {"timestamp": "2026-09-16T10:00:00Z"},
        {"status": "AVISE", "timestamp": "not-a-date"},
    ]
    history = normalize_account_parcel(shipment, include_history=True)["history"]
    assert history == [
        {
            "timestamp": "2026-09-15T10:00:00Z",
            "status": None,
            "raw_status": "EDL_WUNSCHTERMIN",
        },
        {"timestamp": "2026-09-16T10:00:00Z", "status": None, "raw_status": None},
        {
            "timestamp": "not-a-date",
            "status": ParcelStatus.REGISTERED,
            "raw_status": "AVISE",
        },
    ]


def test_history_is_capped_to_the_most_recent_events():
    shipment = delivered_shipment()
    shipment["parcelHistory"] = [
        {"status": "UMSCHLAG_INLAND", "timestamp": f"2026-09-{day:02d}T10:00:00Z"}
        for day in range(1, 29)
    ]
    history = normalize_account_parcel(shipment, include_history=True)["history"]
    assert len(history) == 20
    assert history[-1]["timestamp"] == "2026-09-28T10:00:00Z"


def test_unsupplied_fields_are_none_not_invented():
    """Sender, ETA, pickup point, weight and dimensions are never claimed."""
    shipment = delivered_shipment()
    shipment["atg"]["companyName"] = "Some Delivery Partner"
    shipment["address"]["firstName"] = "Test Receiver"
    shipment["metaInformation"]["destination"] = "Somewhere"
    in_flight = in_flight_shipment()
    in_flight["forecast"] = {"showForecast": True, "deliveryDateBooked": True}
    in_flight["bookedEdl"]["deliveryDate"] = "2026-09-22"
    for source in (shipment, in_flight):
        parcel = normalize_account_parcel(source)
        for field in (
            "sender",
            "planned_from",
            "planned_to",
            "pickup_point",
            "weight",
            "dimensions",
        ):
            assert parcel[field] is None, field


def test_receiver_is_the_address_first_name():
    shipment = delivered_shipment()
    shipment["address"]["firstName"] = "Test Receiver"
    assert normalize_account_parcel(shipment)["receiver"] == "Test Receiver"


def test_pickup_follows_the_status():
    parcel = normalize_account_parcel(in_flight_shipment("PAKETSHOP"))
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True


def test_raw_is_the_untouched_record():
    shipment = delivered_shipment()
    assert normalize_account_parcel(shipment)["raw"] is shipment


def test_raw_status_falls_back_to_the_code_without_display_text():
    shipment = in_flight_shipment()
    del shipment["status"]["text"]
    assert normalize_account_parcel(shipment)["raw_status"] == "ZUSTELLTOUR"


def test_unmapped_status_reports_unknown_and_warns_once(caplog):
    shipment = in_flight_shipment("EDL_WUNSCHTERMIN")
    with caplog.at_level(logging.WARNING):
        first = normalize_account_parcel(shipment)
        normalize_account_parcel(shipment)
    assert first["status"] == ParcelStatus.UNKNOWN
    assert first["raw_status"] == "Deine Sendung ist auf Zustelltour."
    assert caplog.text.count("Unrecognised Hermes account status") == 1
    assert "EDL_WUNSCHTERMIN" in caplog.text
    assert "unrecognised_status.yml" in caplog.text


def test_app_state_families_are_deliberately_unmapped():
    for code in (
        "EDL_WUNSCHNACHBAR",
        "HBX_COURIER_COLLECT",
        "TAN_FEHLVERSUCH_1",
        "INVALID_RECEIVER",
    ):
        assert code not in ACCOUNT_STATUS_MAP


def test_every_mapped_status_lands_on_a_canonical_value():
    assert all(isinstance(value, ParcelStatus) for value in ACCOUNT_STATUS_MAP.values())
    assert ACCOUNT_STATUS_MAP["ZUGESTELLT"] is ParcelStatus.DELIVERED
    assert ACCOUNT_STATUS_MAP["UMSCHLAG_INLAND"] is ParcelStatus.IN_TRANSIT
    assert ACCOUNT_STATUS_MAP["NICHT_ANGETROFFEN_3"] is ParcelStatus.PROBLEM
    assert ACCOUNT_STATUS_MAP["RUECKVERSAND_RETOURE"] is ParcelStatus.RETURNING


def test_the_two_status_maps_are_separate_vocabularies():
    """German account codes must never resolve through the English map."""
    assert ACCOUNT_STATUS_MAP is not TRACKING_STATUS_MAP
    assert (set(ACCOUNT_STATUS_MAP) & set(TRACKING_STATUS_MAP)) == {"ANNOUNCED"}
    assert "ZUGESTELLT" not in TRACKING_STATUS_MAP
    assert "DELIVERED_HOMEDELIVERY" not in ACCOUNT_STATUS_MAP
    assert account_parcels.ACCOUNT_STATUS_MAP is ACCOUNT_STATUS_MAP
