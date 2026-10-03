"""Tests for Hermes diagnostics."""
from unittest.mock import MagicMock

from custom_components.hermes.account.parcels import normalize_account_parcel
from custom_components.hermes.const import ACCOUNT_API_KEY
from custom_components.hermes.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .account.payloads import delivered_shipment


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.data = {}
    entry.options = {"parcels": [{"tracking_code": "12345678901234"}]}
    entry.runtime_data.coordinator.data = [
        {
            "barcode": "12345678901234",
            "sender": "Example Shop",
            "receiver": "Jane Doe",
            "status": "out_for_delivery",
            "raw": {
                "barcode": "12345678901234",
                "recipient": "Jane Doe",
                "recipientAddress": {"city": "Hamburg", "street": "Beispielweg 1"},
            },
        }
    ]
    entry.runtime_data.coordinator.delivered = []
    entry.runtime_data.coordinator.delivered_codes = set()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {
        "incoming_active": 1,
        "delivered": 0,
        "skipped_from_fetch": 0,
    }
    # tracking codes and payload PII are redacted, at every nesting level
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["receiver"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["recipient"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["recipientAddress"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"


async def test_account_diagnostics_redact_credentials_and_receiver_fields(hass):
    """Tokens and the receiver block of GET /shipments must not survive."""
    shipment = delivered_shipment()
    shipment["address"]["firstName"] = "Test Receiver"
    shipment["atg"]["companyName"] = "Some Delivery Partner"
    shipment["metaInformation"]["destination"] = "Somewhere"
    parcel = normalize_account_parcel(shipment, include_history=True)

    entry = MagicMock()
    entry.data = {
        "source": "account",
        "username": "someuser",
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
    }
    entry.options = {}
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = [parcel]
    entry.runtime_data.coordinator.delivered_codes = set()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry_data"]["source"] == "account"
    for key in ("username", "access_token", "refresh_token"):
        assert result["entry_data"][key] == "**REDACTED**"
    dumped = str(result)
    for secret in (
        "someuser",
        "access-secret",
        "refresh-secret",
        "Test Receiver",
        "Some Delivery Partner",
        "Somewhere",
    ):
        assert secret not in dumped
    assert ACCOUNT_API_KEY not in dumped
    delivered = result["delivered"][0]
    assert delivered["status"] == "delivered"
    assert delivered["raw"]["address"] == "**REDACTED**"
    assert delivered["raw"]["atg"]["companyName"] == "**REDACTED**"
    assert delivered["raw"]["metaInformation"]["destination"] == "**REDACTED**"
    assert delivered["raw"]["externalId"] == "**REDACTED**"
