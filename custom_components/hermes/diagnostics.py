"""Diagnostics support for the Hermes parcel tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HermesConfigEntry

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. Over-redacting is
# cheap; under-redacting leaks a user's home address into a GitHub thread.
#
# Diagnostics are pasted into public issues, so redact anything that identifies
# a person, address or specific parcel. The confirmed Paket payload is mostly
# non-PII (`barcode`, `parcelProgress` events), but a real 200 may carry
# sender / recipient / address / zip fields the widget reads — those are
# redacted defensively (over-redacting is harmless). Walk one real response and
# check every leaf when available; nested address blocks are the usual miss.
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "url",
    # carrier payload fields (confirmed + defensively-added)
    "recipient",
    "recipientAddress",
    "RecipientZipCode",
    "PickupZipCode",
    "deliveryAddress",
    "pickupAddress",
    "address",
    "postalCode",
    "zipCode",
    "city",
    "street",
    "email",
    "name",
    "signature",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HermesConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Hermes config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "polling": {
            "current_tier_minutes": coordinator.current_tier_minutes,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
        },
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
