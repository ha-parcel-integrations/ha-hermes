"""Tests for account inbox polling."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hermes.account.client import (
    HermesAccountApiError,
    HermesAccountCompatibilityError,
    HermesAccountReauthRequired,
)
from custom_components.hermes.account.coordinator import HermesAccountCoordinator
from custom_components.hermes.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    DOMAIN,
    MID_INTERVAL_MINUTES,
    ParcelStatus,
)

from .payloads import (
    BARCODE,
    IN_FLIGHT_BARCODE,
    delivered_shipment,
    in_flight_shipment,
    thin_shipment,
)


def _coordinator(hass, shipments=None, **options):
    client = AsyncMock()
    if isinstance(shipments, list) and shipments and isinstance(shipments[0], list):
        client.async_get_shipments.side_effect = shipments
    else:
        client.async_get_shipments.return_value = shipments or []
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 5,
            **options,
        },
    )
    entry.add_to_hass(hass)
    return HermesAccountCoordinator(hass, client, entry), client


async def test_empty_inbox_stays_available_and_keeps_polling(hass):
    coordinator, _ = _coordinator(hass, [])
    assert await coordinator._async_update_data() == []
    assert coordinator.delivered == []
    assert coordinator.update_interval == timedelta(minutes=MID_INTERVAL_MINUTES)
    assert coordinator.current_tier_minutes == MID_INTERVAL_MINUTES
    assert coordinator.delivered_codes == set()


async def test_splits_active_and_delivered_and_survives_a_thin_element(hass):
    coordinator, _ = _coordinator(
        hass, [delivered_shipment(), in_flight_shipment(), thin_shipment()]
    )

    active = await coordinator._async_update_data()

    assert {parcel["barcode"] for parcel in active} == {
        IN_FLIGHT_BARCODE,
        "00000000000000000000",
    }
    assert [parcel["barcode"] for parcel in coordinator.delivered] == [BARCODE]
    unknown = next(p for p in active if p["status"] == ParcelStatus.UNKNOWN)
    assert unknown["delivered"] is False
    assert coordinator.last_success_time is not None


async def test_history_option_is_honoured(hass):
    coordinator, _ = _coordinator(
        hass, [delivered_shipment()], **{CONF_INCLUDE_HISTORY: True}
    )
    await coordinator._async_update_data()
    assert len(coordinator.delivered[0]["history"]) == 7


async def test_rejected_tokens_become_config_entry_auth_failed(hass):
    coordinator, client = _coordinator(hass)
    client.async_get_shipments.side_effect = HermesAccountReauthRequired("x")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_compatibility_failure_is_update_failed_not_reauth(hass):
    coordinator, client = _coordinator(hass)
    client.async_get_shipments.side_effect = HermesAccountCompatibilityError("x")
    with pytest.raises(UpdateFailed, match="needs an update"):
        await coordinator._async_update_data()


async def test_api_error_becomes_update_failed(hass):
    coordinator, client = _coordinator(hass)
    client.async_get_shipments.side_effect = HermesAccountApiError("nope")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_first_refresh_is_silent_then_changes_fire_suite_events(hass):
    coordinator, _ = _coordinator(
        hass,
        [
            [in_flight_shipment("UNTERWEGS")],
            [in_flight_shipment("ZUSTELLTOUR"), in_flight_shipment(barcode="NEW")],
            [delivered_shipment(), in_flight_shipment(barcode="NEW")],
        ],
    )
    fired: dict[str, list] = {}
    for name in ("registered", "status_changed", "delivered"):
        fired[name] = []
        hass.bus.async_listen(f"{DOMAIN}_parcel_{name}", fired[name].append)

    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert not any(fired.values())

    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert [e.data["barcode"] for e in fired["registered"]] == ["NEW"]
    assert fired["status_changed"][0].data["old_status"] == ParcelStatus.IN_TRANSIT
    assert fired["status_changed"][0].data["new_status"] == ParcelStatus.OUT_FOR_DELIVERY

    # The original in-flight parcel is gone and a delivered one appears: a
    # barcode first seen already delivered fires nothing.
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert fired["delivered"] == []


async def test_hop_to_delivered_fires_only_the_delivered_event(hass):
    coordinator, _ = _coordinator(
        hass, [[in_flight_shipment(barcode=BARCODE)], [delivered_shipment()]]
    )
    delivered, changed = [], []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", delivered.append)
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", changed.append)

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert [event.data["barcode"] for event in delivered] == [BARCODE]
    assert changed == []
