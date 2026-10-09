"""Coordinator for the account inbox source."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..const import (
    CONF_INCLUDE_HISTORY,
    DEFAULT_INCLUDE_HISTORY,
    DOMAIN,
    MID_INTERVAL_MINUTES,
    ParcelStatus,
)
from ..events import (
    fire_incoming_change_events,
    snapshot_delivery_times,
    snapshot_states,
)
from ..tracking.parcels import apply_delivered_filter, sort_parcels_by_ts
from .client import (
    HermesAccountApiError,
    HermesAccountClient,
    HermesAccountCompatibilityError,
    HermesAccountReauthRequired,
)
from .parcels import normalize_account_parcel

_LOGGER = logging.getLogger(__name__)


class HermesAccountCoordinator(DataUpdateCoordinator[list[dict]]):
    """Refresh the whole account inbox in one request.

    Publishes the same shape as the tracking coordinator — ``data`` is the
    active parcels, ``delivered`` the retained delivered ones — so every
    platform reads either source unchanged. The inbox is one request, so there
    is nothing to skip and polling never suspends.
    """

    def __init__(
        self, hass: HomeAssistant, client: HermesAccountClient, entry: ConfigEntry
    ) -> None:
        """Initialise a continuously-polled account inbox coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} account",
            update_interval=timedelta(minutes=MID_INTERVAL_MINUTES),
        )
        self._client = client
        self.delivered: list[dict] = []
        # None on the first update deliberately suppresses historical events.
        self._known_state: dict[str, ParcelStatus] | None = None
        self._known_delivery_times: (
            dict[str, tuple[str | None, str | None]] | None
        ) = None
        self._cached_device_id: str | None = None
        self._delivered_codes: set[str] = set()
        self.last_success_time: datetime | None = None
        self.current_tier_minutes: int | None = MID_INTERVAL_MINUTES

    @property
    def delivered_codes(self) -> set[str]:
        """Always empty: the inbox is fetched in one request, nothing is skipped."""
        return self._delivered_codes

    def _device_id(self) -> str | None:
        """Resolve (and cache) this entry's device id for event payloads."""
        if self._cached_device_id is not None:
            return self._cached_device_id
        registry = dr.async_get(self.hass)
        device = next(
            iter(
                dr.async_entries_for_config_entry(registry, self.config_entry.entry_id)
            ),
            None,
        )
        if device is not None:
            self._cached_device_id = device.id
        return self._cached_device_id

    async def _async_update_data(self) -> list[dict]:
        try:
            shipments = await self._client.async_get_shipments()
        except HermesAccountReauthRequired as err:
            raise ConfigEntryAuthFailed("Hermes account needs reauthentication") from err
        except HermesAccountCompatibilityError as err:
            raise UpdateFailed(
                "Hermes refused the account request before checking the login"
            ) from err
        except HermesAccountApiError as err:
            raise UpdateFailed("Unable to update Hermes account inbox") from err

        include_history = bool(
            self.config_entry.options.get(CONF_INCLUDE_HISTORY, DEFAULT_INCLUDE_HISTORY)
        )
        parcels = [
            normalize_account_parcel(raw, include_history=include_history)
            for raw in shipments
        ]
        active = sort_parcels_by_ts(
            [parcel for parcel in parcels if not parcel["delivered"]], "planned_from"
        )
        self.delivered = apply_delivered_filter(
            sort_parcels_by_ts(
                [parcel for parcel in parcels if parcel["delivered"]],
                "delivered_at",
                descending=True,
            ),
            self.config_entry,
        )

        # Active + delivered, combined so the transition to delivered is
        # visible in one set — same shape the tracking coordinator diffs.
        seen = active + self.delivered
        fire_incoming_change_events(
            self.hass,
            seen,
            self._known_state,
            self._known_delivery_times,
            self._device_id(),
        )
        self._known_state = snapshot_states(seen)
        self._known_delivery_times = snapshot_delivery_times(seen)

        self.last_success_time = datetime.now(timezone.utc)
        return active
