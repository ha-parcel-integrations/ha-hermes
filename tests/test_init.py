"""Tests for Hermes setup and unload."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hermes.account.client import (
    HermesAccountClient,
    HermesAccountCompatibilityError,
    HermesAccountReauthRequired,
)
from custom_components.hermes.const import (
    CONF_PARCELS,
    CONF_PASSWORD,
    CONF_SOURCE,
    CONF_TRACKING_CODE,
    CONF_USERNAME,
    DOMAIN,
    SOURCE_ACCOUNT,
    SOURCE_TRACKING,
)
from custom_components.hermes.tracking.api import HermesApiClient, HermesApiError

from .account.payloads import delivered_shipment, in_flight_shipment, thin_shipment
from .tracking.payloads import ACTIVE_CODE
from .tracking.payloads import active_sample as _sample

OTHER_CODE = "22222222222222"


async def test_setup_and_unload(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: [{CONF_TRACKING_CODE: ACTIVE_CODE}]},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.hermes.tracking.api.HermesApiClient.async_get_parcel",
        new=AsyncMock(return_value=_sample()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    # The active parcel produced a per-parcel sensor and the summary sensor.
    incoming = hass.states.get("sensor.hermes_incoming_parcels")
    assert incoming is not None
    assert incoming.state == "1"

    # Services registered on setup...
    assert hass.services.has_service(DOMAIN, "track_parcel")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    # ...and removed on unload (single-instance integration).
    assert not hass.services.has_service(DOMAIN, "track_parcel")


async def test_setup_retries_when_first_refresh_fails(hass):
    """When the first data fetch fails, setup retries from the entry itself.

    The first refresh runs in __init__.py before platforms are forwarded, so a
    failure raises ConfigEntryNotReady from the entry setup (SETUP_RETRY) rather
    than — too late — from a forwarded platform.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: [{CONF_TRACKING_CODE: ACTIVE_CODE}]},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.hermes.tracking.api.HermesApiClient.async_get_parcel",
        new=AsyncMock(side_effect=HermesApiError("Hermes unreachable")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_per_parcel_sensor_spawn_and_remove(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: [{CONF_TRACKING_CODE: ACTIVE_CODE}]},
    )
    entry.add_to_hass(hass)

    mock = AsyncMock(return_value=_sample())
    with patch("custom_components.hermes.tracking.api.HermesApiClient.async_get_parcel", new=mock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{ACTIVE_CODE}"
        )

        # The next poll returns a different tracking code: the summary sensor
        # spawns a new per-parcel sensor and removes the stale one.
        mock.return_value = _sample(OTHER_CODE)
        await entry.runtime_data.coordinator.async_request_refresh()
        await hass.async_block_till_done()

        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{OTHER_CODE}"
        )
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{ACTIVE_CODE}"
            )
            is None
        )


async def test_options_update_applies_live_without_reload(hass):
    """Adding a parcel via options refreshes the coordinator immediately."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: [{CONF_TRACKING_CODE: ACTIVE_CODE}]},
    )
    entry.add_to_hass(hass)

    mock = AsyncMock(return_value=_sample())
    with patch("custom_components.hermes.tracking.api.HermesApiClient.async_get_parcel", new=mock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        mock.side_effect = lambda code: _sample(code)
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_PARCELS: [
                    {CONF_TRACKING_CODE: ACTIVE_CODE},
                    {CONF_TRACKING_CODE: OTHER_CODE},
                ],
            },
        )
        await hass.async_block_till_done()

    incoming = hass.states.get("sensor.hermes_incoming_parcels")
    assert incoming.state == "2"


# --- account source ---------------------------------------------------------

_ACCOUNT_CLIENT = "custom_components.hermes.account.client.HermesAccountClient."


def _account_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account:someuser",
        data={
            CONF_SOURCE: SOURCE_ACCOUNT,
            CONF_USERNAME: "someuser",
            "access_token": "access-1",
            "refresh_token": "refresh-1",
        },
        # The fixture's delivery is dated, so retain by count, not by age.
        options={"delivered_filter_type": "parcels", "delivered_filter_amount": 5},
    )
    entry.add_to_hass(hass)
    return entry


def _reauth_flows(hass) -> list:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
    ]


async def test_account_entry_sets_up_from_the_inbox_without_services(hass):
    entry = _account_entry(hass)
    with patch(
        _ACCOUNT_CLIENT + "async_get_shipments",
        new=AsyncMock(
            return_value=[delivered_shipment(), in_flight_shipment(), thin_shipment()]
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data.client, HermesAccountClient)
    # One in-flight parcel plus the thin element; the delivered one is separate.
    assert hass.states.get("sensor.hermes_someuser_incoming_parcels").state == "2"
    assert hass.states.get("sensor.hermes_someuser_delivered_parcels").state == "1"
    # An account entry has no tracked list, so it registers no services.
    assert not hass.services.has_service(DOMAIN, "track_parcel")

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_rejected_account_tokens_at_setup_start_reauth(hass):
    """The coordinator must raise ConfigEntryAuthFailed itself, or HA retries forever."""
    entry = _account_entry(hass)
    with patch(
        _ACCOUNT_CLIENT + "async_get_shipments",
        new=AsyncMock(side_effect=HermesAccountReauthRequired("x")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass)) == 1


async def test_rejected_account_tokens_while_running_start_reauth(hass):
    entry = _account_entry(hass)
    with patch(
        _ACCOUNT_CLIENT + "async_get_shipments", new=AsyncMock(return_value=[])
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert _reauth_flows(hass) == []
    with patch(
        _ACCOUNT_CLIENT + "async_get_shipments",
        new=AsyncMock(side_effect=HermesAccountReauthRequired("x")),
    ):
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
    assert len(_reauth_flows(hass)) == 1


async def test_rejected_app_key_never_starts_reauth(hass):
    """A rotated key is the integration's problem: no password prompt."""
    entry = _account_entry(hass)
    with patch(
        _ACCOUNT_CLIENT + "async_get_shipments",
        new=AsyncMock(side_effect=HermesAccountCompatibilityError("x")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _reauth_flows(hass) == []


async def test_rotated_account_tokens_are_persisted_on_the_entry(hass):
    entry = _account_entry(hass)
    with patch(
        _ACCOUNT_CLIENT + "async_get_shipments", new=AsyncMock(return_value=[])
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    await entry.runtime_data.client._token_callback(
        {"access_token": "access-2", "refresh_token": "refresh-2"}
    )
    assert entry.data["access_token"] == "access-2"
    assert entry.data["refresh_token"] == "refresh-2"
    assert entry.data[CONF_USERNAME] == "someuser"
    assert CONF_PASSWORD not in entry.data


async def test_tracking_and_account_entries_run_side_by_side(hass):
    tracking = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_SOURCE: SOURCE_TRACKING},
        options={CONF_PARCELS: [{CONF_TRACKING_CODE: ACTIVE_CODE}]},
    )
    tracking.add_to_hass(hass)
    account = _account_entry(hass)
    with patch(
        "custom_components.hermes.tracking.api.HermesApiClient.async_get_parcel",
        new=AsyncMock(return_value=_sample()),
    ), patch(
        _ACCOUNT_CLIENT + "async_get_shipments", new=AsyncMock(return_value=[])
    ):
        # Setting up the first entry of a domain sets up all of them.
        assert await hass.config_entries.async_setup(tracking.entry_id)
        await hass.async_block_till_done()

    assert tracking.state is ConfigEntryState.LOADED
    assert account.state is ConfigEntryState.LOADED

    assert hass.services.has_service(DOMAIN, "track_parcel")

    # Unloading the account entry leaves the tracking hub's services alone...
    assert await hass.config_entries.async_unload(account.entry_id)
    assert hass.services.has_service(DOMAIN, "track_parcel")
    # ...and unloading the tracking hub removes them.
    assert await hass.config_entries.async_unload(tracking.entry_id)
    assert not hass.services.has_service(DOMAIN, "track_parcel")


async def test_entry_without_a_source_key_is_a_tracking_hub(hass):
    """Entries from 1.1.x carry no source key; the default is the migration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={CONF_PARCELS: [{CONF_TRACKING_CODE: ACTIVE_CODE}]},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.hermes.tracking.api.HermesApiClient.async_get_parcel",
        new=AsyncMock(return_value=_sample()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert isinstance(entry.runtime_data.client, HermesApiClient)
    assert hass.services.has_service(DOMAIN, "track_parcel")


async def test_account_coordinator_resolves_and_caches_its_device_id(hass):
    entry = _account_entry(hass)
    with patch(
        _ACCOUNT_CLIENT + "async_get_shipments", new=AsyncMock(return_value=[])
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    device_id = coordinator._device_id()
    assert device_id is not None
    assert coordinator._device_id() == device_id
