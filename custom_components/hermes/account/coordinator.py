"""Coordinator for the account inbox source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
from ..contents import ContentsStore, normalize_code
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

    config_entry: ConfigEntry

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
        self.contents_store = ContentsStore(hass, entry.entry_id)
        # Every barcode the inbox lists, delivered ones past the retention
        # filter included: update_contents asks which entry a code belongs to.
        self.known_codes: frozenset[str] = frozenset()
        self.delivered: list[dict] = []
        # id(published parcel) -> the barcode its contents are stored under.
        self._parcel_codes: dict[int, str] = {}
        # id(published parcel) -> the text the carrier sent, which a cleared
        # user value falls back to.
        self._carrier_contents: dict[int, str | None] = {}
        # None on the first update deliberately suppresses historical events.
        self._known_state: dict[str, ParcelStatus] | None = None
        self._known_delivery_times: dict[str, tuple[str | None, str | None]] | None = (
            None
        )
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

    def _apply_contents(self, parcel: dict, code: object) -> dict:
        """Put the user's own contents text over the carrier's, when there is one."""
        user_value = self.contents_store.get(code)
        if user_value is not None:
            parcel["contents"] = user_value
        return parcel

    @callback
    def async_reapply_contents(self) -> None:
        """Re-read the contents store into the published parcels, without a poll."""
        for parcel in [*(self.data or []), *self.delivered]:
            code = self._parcel_codes.get(id(parcel), parcel.get("barcode") or "")
            parcel["contents"] = self._carrier_contents.get(id(parcel))
            self._apply_contents(parcel, code)
        self.async_update_listeners()

    async def _async_update_data(self) -> list[dict]:
        try:
            shipments = await self._client.async_get_shipments()
        except HermesAccountReauthRequired as err:
            raise ConfigEntryAuthFailed(
                "Hermes account needs reauthentication"
            ) from err
        except HermesAccountCompatibilityError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="request_refused"
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
        self._carrier_contents = {id(p): p.get("contents") for p in parcels}
        for parcel in parcels:
            self._apply_contents(parcel, parcel["barcode"] or "")
        self._parcel_codes = {id(p): p["barcode"] or "" for p in parcels}
        self.known_codes = frozenset(
            normalize_code(parcel["barcode"]) for parcel in parcels if parcel["barcode"]
        )
        active = sort_parcels_by_ts(
            [parcel for parcel in parcels if not parcel["delivered"]], "planned_from"
        )
        delivered_sorted = sort_parcels_by_ts(
            [parcel for parcel in parcels if parcel["delivered"]],
            "delivered_at",
            descending=True,
        )
        self.delivered = apply_delivered_filter(delivered_sorted, self.config_entry)

        # Active + delivered, combined so the transition to delivered is
        # visible in one set — same shape the tracking coordinator diffs.
        # Events and remembered state cover every parcel; the retention option
        # only limits what the delivered sensor shows.
        seen = active + delivered_sorted
        fire_incoming_change_events(
            self.hass,
            seen,
            self._known_state,
            self._known_delivery_times,
            self._device_id(),
        )
        self._known_state = snapshot_states(seen)
        self._known_delivery_times = snapshot_delivery_times(seen)

        self.last_success_time = datetime.now(UTC)
        return active
