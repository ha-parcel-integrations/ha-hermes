"""The device every entity of this integration belongs to.

One place, because sensors, the button and the calendar must all land on the
*same* device entry — and because the account-based variant only has to change
this file to name devices per account.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_SOURCE, CONF_USERNAME, DOMAIN, SOURCE_ACCOUNT

CONFIGURATION_URL = "https://www.myhermes.de"

ATTRIBUTION = "Data provided by Hermes"


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the DeviceInfo shared by every entity of this hub.

    An account entry carries its username in the device name so a household
    with more than one account keeps them apart.
    """
    username = entry.data.get(CONF_USERNAME)
    is_account = entry.data.get(CONF_SOURCE) == SOURCE_ACCOUNT
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Hermes ({username})" if is_account and username else "Hermes",
        manufacturer="Hermes Germany",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=CONFIGURATION_URL,
    )
