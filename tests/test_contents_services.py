"""Tests for the contents action, the track_parcel field and the store lifecycle."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.hermes.account.coordinator import HermesAccountCoordinator
from custom_components.hermes.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_PARCELS,
    CONF_SOURCE,
    CONF_TRACKING_CODE,
    CONF_USERNAME,
    DOMAIN,
    SOURCE_ACCOUNT,
)
from custom_components.hermes.tracking import coordinator as module
from custom_components.hermes.tracking.coordinator import HermesCoordinator

from .account.payloads import (
    BARCODE as ACCOUNT_DELIVERED,
    IN_FLIGHT_BARCODE as ACCOUNT_CODE,
    delivered_shipment,
    in_flight_shipment,
)
from .tracking.payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    active_sample,
    delivered_sample,
)

CLIENT = "custom_components.hermes.tracking.api.HermesApiClient"
ACCOUNT_CLIENT = "custom_components.hermes.account.client.HermesAccountClient"
UNTRACKED = "55555555555555"
STORE_KEY = f"{DOMAIN}.contents.%s"


async def _setup(hass, codes: list[str] | None = None, unique_id: str = DOMAIN):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        options={CONF_PARCELS: [{CONF_TRACKING_CODE: code} for code in codes or []]},
    )
    entry.add_to_hass(hass)
    with patch(
        f"{CLIENT}.async_get_parcel",
        new=AsyncMock(side_effect=active_sample),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _setup_account(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account:someuser",
        data={CONF_SOURCE: SOURCE_ACCOUNT, CONF_USERNAME: "someuser"},
        options={
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 5,
        },
    )
    entry.add_to_hass(hass)
    with patch(
        f"{ACCOUNT_CLIENT}.async_get_shipments",
        new=AsyncMock(
            return_value=[in_flight_shipment(), delivered_shipment()],
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@contextmanager
def _polls():
    with (
        patch(f"{CLIENT}.async_get_parcel", new=AsyncMock(side_effect=active_sample)),
        patch(
            f"{ACCOUNT_CLIENT}.async_get_shipments",
            new=AsyncMock(return_value=[in_flight_shipment(), delivered_shipment()]),
        ),
    ):
        yield


async def _call(hass, service: str, data: dict) -> None:
    with _polls():
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
        await hass.async_block_till_done()
        # A refresh requested inside the debouncer's cooldown runs after it.
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()


@contextmanager
def _no_poll():
    """Patch every way a coordinator could ask the carrier.

    Yields a callable that asserts none of them was used.
    """
    with (
        patch.object(HermesCoordinator, "async_request_refresh", AsyncMock()) as hub,
        patch.object(
            HermesAccountCoordinator, "async_request_refresh", AsyncMock()
        ) as inbox_refresh,
        patch(f"{CLIENT}.async_get_parcel", new=AsyncMock()) as fetch,
        patch(f"{ACCOUNT_CLIENT}.async_get_shipments", new=AsyncMock()) as inbox,
    ):

        def assert_no_poll() -> None:
            for mock in (hub, inbox_refresh, fetch, inbox):
                mock.assert_not_called()

        yield assert_no_poll


async def _call_no_poll(hass, service: str, data: dict) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    await hass.async_block_till_done()


def _contents(entry: MockConfigEntry, code: str) -> str | None:
    parcels = {p["barcode"]: p for p in entry.runtime_data.coordinator.data}
    return parcels[code]["contents"]


def _store(entry: MockConfigEntry):
    return entry.runtime_data.coordinator.contents_store


async def test_a_parcel_has_no_contents_without_a_stored_value(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    assert _contents(entry, ACTIVE_CODE) is None


async def test_update_contents_sets_replaces_and_clears(hass):
    entry = await _setup(hass, [ACTIVE_CODE])

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": " Running  shoes "},
    )
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Winter socks"},
    )
    assert _contents(entry, ACTIVE_CODE) == "Winter socks"

    await _call(
        hass, "update_contents", {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "  "}
    )
    assert _contents(entry, ACTIVE_CODE) is None


async def test_update_contents_without_text_clears(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    await _call(hass, "update_contents", {CONF_TRACKING_CODE: ACTIVE_CODE})

    assert _contents(entry, ACTIVE_CODE) is None


async def test_update_contents_normalizes_the_code(hass):
    entry = await _setup(hass, ["EXAMPLE000999"])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: " example000999 ", "contents": "Running shoes"},
    )
    assert _store(entry).get("EXAMPLE000999") == "Running shoes"


async def test_update_contents_works_for_a_code_that_is_not_tracked(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: UNTRACKED, "contents": "Running shoes"},
    )

    assert _store(entry).get(UNTRACKED) == "Running shoes"
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]


async def test_update_contents_reapplies_only_when_something_changed(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    data = {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"}
    with (
        _no_poll() as assert_no_poll,
        patch.object(coordinator, "async_update_listeners") as listeners,
    ):
        await _call_no_poll(hass, "update_contents", data)
        assert listeners.call_count == 1
        await _call_no_poll(hass, "update_contents", data)
        assert listeners.call_count == 1
        # Clearing a code no entry lists touches nothing.
        await _call_no_poll(hass, "update_contents", {CONF_TRACKING_CODE: UNTRACKED})
        assert listeners.call_count == 1
        await _call_no_poll(hass, "update_contents", {CONF_TRACKING_CODE: ACTIVE_CODE})
        assert listeners.call_count == 2
    assert_no_poll()


async def test_an_unchanged_value_writes_nothing(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    store = _store(entry)
    with patch.object(store._store, "async_delay_save") as save:
        assert store.async_set(ACTIVE_CODE, "Running shoes") is True
        assert save.call_count == 1
        assert store.async_set(ACTIVE_CODE, " Running shoes ") is False
        assert store.async_set(UNTRACKED, None) is False
        assert save.call_count == 1


async def test_update_contents_rejects_an_empty_code(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "update_contents", {CONF_TRACKING_CODE: " "})


async def test_update_contents_needs_a_loaded_entry(hass):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "update_contents",
            {CONF_TRACKING_CODE: ACTIVE_CODE},
            blocking=True,
        )


async def test_update_contents_ignores_an_entry_that_is_not_loaded(hass):
    entry = await _setup(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
        )


async def test_track_parcel_stores_contents_for_a_new_code(hass):
    entry = await _setup(hass)
    await _call(
        hass,
        "track_parcel",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"


async def test_track_parcel_without_contents_is_unchanged(hass):
    entry = await _setup(hass)
    await _call(hass, "track_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE})

    assert _store(entry).get(ACTIVE_CODE) is None
    assert _contents(entry, ACTIVE_CODE) is None


async def test_track_parcel_replaces_and_clears_contents_of_a_tracked_code(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    track = {CONF_TRACKING_CODE: ACTIVE_CODE}

    await _call(hass, "track_parcel", {**track, "contents": "Running shoes"})
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"

    await _call(hass, "track_parcel", {**track, "contents": "Winter socks"})
    assert _contents(entry, ACTIVE_CODE) == "Winter socks"

    await _call(hass, "track_parcel", {**track, "contents": ""})
    assert _contents(entry, ACTIVE_CODE) is None
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]


async def test_track_parcel_on_a_tracked_code_does_not_poll(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    data = {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"}
    with (
        _no_poll() as assert_no_poll,
        patch.object(coordinator, "async_update_listeners") as listeners,
    ):
        await _call_no_poll(hass, "track_parcel", data)
        assert _contents(entry, ACTIVE_CODE) == "Running shoes"
        await _call_no_poll(hass, "track_parcel", data)
        assert listeners.call_count == 1
        await _call_no_poll(hass, "track_parcel", {**data, "contents": ""})
        assert listeners.call_count == 2
    assert _contents(entry, ACTIVE_CODE) is None
    assert_no_poll()


async def test_track_parcel_with_contents_needs_a_loaded_hub(hass):
    entry = await _setup(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "track_parcel",
            {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
        )


async def test_untrack_parcel_drops_the_contents(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    await _call(hass, "untrack_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE})

    assert _store(entry).get(ACTIVE_CODE) is None
    assert entry.options[CONF_PARCELS] == []


async def test_untrack_parcel_skips_a_hub_that_is_not_loaded(hass):
    asleep = await _setup(hass, [ACTIVE_CODE])
    entry = await _setup(hass, [], unique_id="second")
    # _resolve_entry takes the first hub; unload it, leaving a stale store to skip.
    assert await hass.config_entries.async_unload(asleep.entry_id)
    assert entry.state is ConfigEntryState.LOADED

    await hass.services.async_call(
        DOMAIN, "untrack_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE}, blocking=True
    )

    assert asleep.options[CONF_PARCELS] == []


async def test_a_stored_value_survives_a_restart_of_the_entry(hass, hass_storage):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )
    await _store(entry)._store.async_save(_store(entry)._data_to_save())

    assert await hass.config_entries.async_unload(entry.entry_id)
    with _polls():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert _contents(entry, ACTIVE_CODE) == "Running shoes"


async def test_an_entry_without_a_store_file_sets_up_and_loads_empty(
    hass, hass_storage
):
    assert not [key for key in hass_storage if key.startswith(f"{DOMAIN}.contents.")]
    entry = await _setup(hass, [ACTIVE_CODE])
    assert entry.state is ConfigEntryState.LOADED
    assert _contents(entry, ACTIVE_CODE) is None


@pytest.mark.parametrize("kind", ["hub", "account"])
async def test_removing_the_entry_removes_its_store(hass, hass_storage, kind):
    if kind == "hub":
        entry, code = await _setup(hass, [ACTIVE_CODE]), ACTIVE_CODE
    else:
        entry, code = await _setup_account(hass), ACCOUNT_CODE
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: code, "contents": "Running shoes"},
    )
    store = _store(entry)
    await store._store.async_save(store._data_to_save())
    key = STORE_KEY % entry.entry_id
    assert key in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


async def test_a_contents_change_alone_fires_no_event(hass):
    await _setup(hass, [ACTIVE_CODE])
    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", events.append)
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", events.append)
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", events.append)

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    assert events == []


# ---------------------------------------------------------------------------
# overlay on the coordinators
# ---------------------------------------------------------------------------


async def test_user_contents_reaches_the_delivered_list_and_events(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    coordinator.contents_store.async_set(ACTIVE_CODE, "Running shoes")
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 10,
        },
    )
    delivered = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", delivered.append)

    with patch(
        f"{CLIENT}.async_get_parcel",
        new=AsyncMock(return_value=delivered_sample(ACTIVE_CODE)),
    ):
        await coordinator._async_update_data()
        await hass.async_block_till_done()

    assert coordinator.delivered[0]["contents"] == "Running shoes"
    assert delivered[0].data["contents"] == "Running shoes"


async def test_user_contents_is_keyed_on_the_requested_code(hass):
    """A payload carrying another number still finds the value stored for the code."""
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    coordinator.contents_store.async_set(ACTIVE_CODE, "Running shoes")

    with patch(
        f"{CLIENT}.async_get_parcel",
        new=AsyncMock(return_value=active_sample(DELIVERED_CODE)),
    ):
        data = await coordinator._async_update_data()

    assert data[0]["barcode"] == DELIVERED_CODE
    assert data[0]["contents"] == "Running shoes"


async def test_user_contents_overlays_the_carrier_value(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    real = module.normalize_parcel

    def carrier_text(raw, **kwargs):
        parcel = real(raw, **kwargs)
        parcel["contents"] = "Carrier text"
        return parcel

    with (
        patch.object(module, "normalize_parcel", side_effect=carrier_text),
        patch(
            f"{CLIENT}.async_get_parcel",
            new=AsyncMock(return_value=active_sample(ACTIVE_CODE)),
        ),
    ):
        assert (await coordinator._async_update_data())[0]["contents"] == (
            "Carrier text"
        )
        coordinator.contents_store.async_set(ACTIVE_CODE, "Running shoes")
        assert (await coordinator._async_update_data())[0]["contents"] == (
            "Running shoes"
        )
        coordinator.contents_store.async_set(ACTIVE_CODE, None)
        assert (await coordinator._async_update_data())[0]["contents"] == (
            "Carrier text"
        )


async def test_account_overlay_covers_active_and_delivered(hass):
    account = await _setup_account(hass)
    coordinator = account.runtime_data.coordinator
    assert isinstance(coordinator, HermesAccountCoordinator)
    coordinator.contents_store.async_set(ACCOUNT_CODE, "Running shoes")
    coordinator.contents_store.async_set(ACCOUNT_DELIVERED, "Winter socks")

    with patch(
        f"{ACCOUNT_CLIENT}.async_get_shipments",
        new=AsyncMock(return_value=[in_flight_shipment(), delivered_shipment()]),
    ):
        active = await coordinator._async_update_data()

    assert active[0]["contents"] == "Running shoes"
    assert coordinator.delivered[0]["contents"] == "Winter socks"


async def test_known_codes_list_every_code_the_entry_holds(hass):
    hub = await _setup(hass, [ACTIVE_CODE])
    account = await _setup_account(hass)

    assert hub.runtime_data.coordinator.known_codes == {ACTIVE_CODE}
    assert account.runtime_data.coordinator.known_codes == {
        ACCOUNT_CODE,
        ACCOUNT_DELIVERED,
    }


async def test_account_entries_take_contents_too(hass):
    account = await _setup_account(hass)

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACCOUNT_CODE, "contents": "Running shoes"},
    )

    assert _contents(account, ACCOUNT_CODE) == "Running shoes"


# ---------------------------------------------------------------------------
# several entries
# ---------------------------------------------------------------------------


async def test_update_contents_goes_to_the_entry_that_lists_the_code(hass):
    hub = await _setup(hass, [ACTIVE_CODE])
    account = await _setup_account(hass)

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    assert _store(hub).get(ACTIVE_CODE) == "Running shoes"
    assert _store(account).get(ACTIVE_CODE) is None


async def test_update_contents_goes_to_every_entry_that_lists_the_code(hass):
    home = await _setup(hass, [ACTIVE_CODE])
    work = await _setup(hass, [ACTIVE_CODE], unique_id="second")

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    assert _store(home).get(ACTIVE_CODE) == "Running shoes"
    assert _store(work).get(ACTIVE_CODE) == "Running shoes"


async def test_update_contents_reaches_a_hub_and_an_account_alike(hass):
    hub = await _setup(hass, [ACCOUNT_CODE])
    account = await _setup_account(hass)

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACCOUNT_CODE, "contents": "Running shoes"},
    )

    assert _store(hub).get(ACCOUNT_CODE) == "Running shoes"
    assert _store(account).get(ACCOUNT_CODE) == "Running shoes"


async def test_update_contents_with_several_entries_and_no_match_needs_an_entry(hass):
    hub = await _setup(hass, [ACTIVE_CODE])
    account = await _setup_account(hass)

    with pytest.raises(ServiceValidationError) as error:
        await _call(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: UNTRACKED, "contents": "Running shoes"},
        )

    assert error.value.translation_key == "update_contents_entry_required"
    assert _store(hub).get(UNTRACKED) is None
    assert _store(account).get(UNTRACKED) is None


async def test_config_entry_id_restricts_and_stores_an_unknown_code(hass):
    hub = await _setup(hass, [ACTIVE_CODE])
    account = await _setup_account(hass)

    await _call(
        hass,
        "update_contents",
        {
            CONF_TRACKING_CODE: UNTRACKED,
            "contents": "Running shoes",
            "config_entry_id": account.entry_id,
        },
    )
    await _call(
        hass,
        "update_contents",
        {
            CONF_TRACKING_CODE: ACTIVE_CODE,
            "contents": "Winter socks",
            "config_entry_id": hub.entry_id,
        },
    )

    assert _store(account).get(UNTRACKED) == "Running shoes"
    assert _store(hub).get(UNTRACKED) is None
    assert _store(hub).get(ACTIVE_CODE) == "Winter socks"
    assert _store(account).get(ACTIVE_CODE) is None


async def test_config_entry_id_must_name_a_loaded_entry(hass):
    await _setup(hass, [ACTIVE_CODE])
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACTIVE_CODE, "config_entry_id": "missing"},
        )


# ---------------------------------------------------------------------------
# service registration
# ---------------------------------------------------------------------------


async def test_an_account_alone_registers_only_update_contents(hass):
    account = await _setup_account(hass)

    assert hass.services.has_service(DOMAIN, "update_contents")
    assert not hass.services.has_service(DOMAIN, "track_parcel")
    assert not hass.services.has_service(DOMAIN, "untrack_parcel")

    assert await hass.config_entries.async_unload(account.entry_id)
    assert not hass.services.has_service(DOMAIN, "update_contents")


async def test_unloading_one_entry_keeps_the_services_the_others_need(hass):
    hub = await _setup(hass, [ACTIVE_CODE])
    account = await _setup_account(hass)
    assert hass.services.has_service(DOMAIN, "track_parcel")

    assert await hass.config_entries.async_unload(hub.entry_id)
    assert hass.services.has_service(DOMAIN, "update_contents")
    assert not hass.services.has_service(DOMAIN, "track_parcel")

    assert await hass.config_entries.async_unload(account.entry_id)
    assert not hass.services.has_service(DOMAIN, "update_contents")


async def test_a_hub_after_an_account_still_registers_the_hub_services(hass):
    await _setup_account(hass)
    await _setup(hass, [ACTIVE_CODE])

    assert hass.services.has_service(DOMAIN, "track_parcel")
    assert hass.services.has_service(DOMAIN, "untrack_parcel")


# ---------------------------------------------------------------------------
# a contents change never polls the carrier
# ---------------------------------------------------------------------------


async def test_update_contents_reaches_the_account_without_a_poll(hass):
    account = await _setup_account(hass)
    coordinator = account.runtime_data.coordinator
    with (
        _no_poll() as assert_no_poll,
        patch.object(coordinator, "async_update_listeners") as listeners,
    ):
        await _call_no_poll(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACCOUNT_CODE, "contents": "Running shoes"},
        )
        assert listeners.call_count == 1
        await _call_no_poll(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACCOUNT_CODE, "contents": "Running shoes"},
        )
        assert listeners.call_count == 1
    assert_no_poll()
    assert _contents(account, ACCOUNT_CODE) == "Running shoes"


async def test_reapply_reaches_delivered_parcels(hass):
    account = await _setup_account(hass)
    coordinator = account.runtime_data.coordinator
    assert coordinator.delivered
    with _no_poll() as assert_no_poll:
        await _call_no_poll(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACCOUNT_DELIVERED, "contents": "Winter socks"},
        )
    assert_no_poll()
    assert coordinator.delivered[0]["contents"] == "Winter socks"

    with _no_poll():
        await _call_no_poll(
            hass, "update_contents", {CONF_TRACKING_CODE: ACCOUNT_DELIVERED}
        )
    assert coordinator.delivered[0]["contents"] is None


async def test_reapply_reaches_a_delivered_tracked_parcel(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 10,
        },
    )
    with patch(
        f"{CLIENT}.async_get_parcel",
        new=AsyncMock(return_value=delivered_sample(ACTIVE_CODE)),
    ):
        await coordinator._async_update_data()
    assert coordinator.delivered

    with _no_poll() as assert_no_poll:
        await _call_no_poll(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
        )
    assert_no_poll()
    assert coordinator.delivered[0]["contents"] == "Running shoes"


async def test_a_barcodeless_parcel_keeps_its_contents_after_reapply_and_a_poll(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    real = module.normalize_parcel

    def without_barcode(raw, **kwargs):
        parcel = real(raw, **kwargs)
        parcel["barcode"] = None
        return parcel

    with (
        patch.object(module, "normalize_parcel", side_effect=without_barcode),
        patch(
            f"{CLIENT}.async_get_parcel",
            new=AsyncMock(return_value=active_sample(ACTIVE_CODE)),
        ),
    ):
        await coordinator._async_update_data()
        coordinator.data = await coordinator._async_update_data()
        coordinator.contents_store.async_set(ACTIVE_CODE, "Running shoes")
        coordinator.async_reapply_contents()
        assert coordinator.data[0]["contents"] == "Running shoes"
        coordinator.data = await coordinator._async_update_data()
        assert coordinator.data[0]["contents"] == "Running shoes"


async def test_a_different_response_barcode_keeps_the_text_after_reapply(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    coordinator.contents_store.async_set(ACTIVE_CODE, "Running shoes")

    with patch(
        f"{CLIENT}.async_get_parcel",
        new=AsyncMock(return_value=active_sample(DELIVERED_CODE)),
    ):
        coordinator.data = await coordinator._async_update_data()
    assert coordinator.data[0]["barcode"] == DELIVERED_CODE

    coordinator.contents_store.async_set(ACTIVE_CODE, "Winter socks")
    coordinator.async_reapply_contents()

    assert coordinator.data[0]["contents"] == "Winter socks"


async def test_two_entries_listing_the_code_are_both_reapplied_without_a_poll(hass):
    home = await _setup(hass, [ACTIVE_CODE])
    work = await _setup(hass, [ACTIVE_CODE], unique_id="second")
    with (
        _no_poll() as assert_no_poll,
        (
            patch.object(home.runtime_data.coordinator, "async_update_listeners")
        ) as home_listeners,
        patch.object(
            work.runtime_data.coordinator, "async_update_listeners"
        ) as work_listeners,
    ):
        await _call_no_poll(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
        )
    assert_no_poll()
    assert home_listeners.call_count == 1
    assert work_listeners.call_count == 1
    assert _contents(home, ACTIVE_CODE) == "Running shoes"
    assert _contents(work, ACTIVE_CODE) == "Running shoes"


async def test_a_new_code_with_contents_still_refreshes(hass):
    entry = await _setup(hass)
    await _call(
        hass,
        "track_parcel",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"


async def _setup_account_with_description(hass) -> MockConfigEntry:
    described = in_flight_shipment()
    described["description"] = "Carrier text"
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account:someuser",
        data={CONF_SOURCE: SOURCE_ACCOUNT, CONF_USERNAME: "someuser"},
    )
    entry.add_to_hass(hass)
    with patch(
        f"{ACCOUNT_CLIENT}.async_get_shipments",
        new=AsyncMock(return_value=[described, delivered_shipment()]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_account_reapply_keeps_carrier_text_for_other_codes(hass):
    account = await _setup_account_with_description(hass)
    assert _contents(account, ACCOUNT_CODE) == "Carrier text"
    with _no_poll() as assert_no_poll:
        await _call_no_poll(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACCOUNT_DELIVERED, "contents": "Winter socks"},
        )
    assert_no_poll()
    assert _contents(account, ACCOUNT_CODE) == "Carrier text"


async def test_account_user_value_beats_carrier_text_and_clearing_reverts(hass):
    account = await _setup_account_with_description(hass)
    coordinator = account.runtime_data.coordinator
    set_value = {CONF_TRACKING_CODE: ACCOUNT_CODE, "contents": "Running shoes"}
    with _no_poll():
        await _call_no_poll(hass, "update_contents", set_value)
    assert _contents(account, ACCOUNT_CODE) == "Running shoes"

    # A poll keeps the user value; the carrier text stays behind it.
    described = in_flight_shipment()
    described["description"] = "Carrier text"
    with patch(
        f"{ACCOUNT_CLIENT}.async_get_shipments",
        new=AsyncMock(return_value=[described, delivered_shipment()]),
    ):
        coordinator.data = await coordinator._async_update_data()
    assert _contents(account, ACCOUNT_CODE) == "Running shoes"

    with _no_poll():
        await _call_no_poll(hass, "update_contents", {CONF_TRACKING_CODE: ACCOUNT_CODE})
    assert _contents(account, ACCOUNT_CODE) == "Carrier text"

    with patch(
        f"{ACCOUNT_CLIENT}.async_get_shipments",
        new=AsyncMock(return_value=[described, delivered_shipment()]),
    ):
        coordinator.data = await coordinator._async_update_data()
    assert _contents(account, ACCOUNT_CODE) == "Carrier text"
