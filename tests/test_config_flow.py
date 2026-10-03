"""Tests for the Hermes config and options flow."""
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hermes.account.client import (
    HermesAccountApiError,
    HermesAccountCompatibilityError,
    HermesAccountInvalidCredentials,
)
from custom_components.hermes.config_flow import (
    normalize_tracking_code,
    valid_tracking_code,
)
from custom_components.hermes.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_PASSWORD,
    CONF_SOURCE,
    CONF_TRACKING_CODE,
    CONF_USERNAME,
    DOMAIN,
    SOURCE_ACCOUNT,
    SOURCE_TRACKING,
)


def test_normalize_tracking_code_strips_and_uppercases():
    assert normalize_tracking_code("1234 5678-9012 34") == "12345678901234"
    assert normalize_tracking_code("") == ""
    assert normalize_tracking_code(None) == ""


def test_valid_tracking_code_accepts_any_non_empty_code():
    # Hermes' real formats vary too much to gate on (e.g. some codes carry a
    # leading letter, as shown on myhermes.de — issue #8); only emptiness is
    # rejected.
    assert valid_tracking_code("12345678901234")
    assert valid_tracking_code("H1003660779926301068")
    assert not valid_tracking_code("")


async def _pick(hass, source: str):
    """Open the flow and choose a source from the opening menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "menu"
    assert result["menu_options"] == ["account", "tracking"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": source}
    )


async def test_tracking_source_creates_hub_without_input(hass):
    """No account, no postcode — the entry is created straight away."""
    result = await _pick(hass, "tracking")
    assert result["type"] == "create_entry"
    assert result["title"] == "Hermes"
    assert result["data"] == {CONF_SOURCE: SOURCE_TRACKING}
    assert result["options"][CONF_PARCELS] == []
    assert result["result"].unique_id == DOMAIN


async def test_second_tracking_hub_rejected(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await _pick(hass, "tracking")
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_account_can_be_added_next_to_a_tracking_hub(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await _pick(hass, "account")
    assert result["type"] == "form"
    assert result["step_id"] == "account"


_LOGIN = "custom_components.hermes.account.client.HermesAccountClient.async_login"
_TOKENS = {"access_token": "access-1", "refresh_token": "refresh-1"}


async def _submit_account(hass, username="  SomeUser ", password="pw"):
    result = await _pick(hass, "account")
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: username, CONF_PASSWORD: password}
    )


async def test_account_login_stores_tokens_and_never_the_password(hass):
    with patch(_LOGIN, new=AsyncMock(return_value=_TOKENS)) as login:
        result = await _submit_account(hass)

    login.assert_awaited_once_with("someuser", "pw")
    assert result["type"] == "create_entry"
    assert result["title"] == "Hermes (someuser)"
    assert result["data"] == {
        CONF_SOURCE: SOURCE_ACCOUNT,
        CONF_USERNAME: "someuser",
        **_TOKENS,
    }
    assert CONF_PASSWORD not in result["data"]
    assert "pw" not in str(result["data"]) + str(result["options"])
    # Keyed on the lower-cased username — not an email address.
    assert result["result"].unique_id == "account:someuser"


async def test_account_form_asks_for_a_username_not_an_email(hass):
    result = await _pick(hass, "account")
    assert [str(key) for key in result["data_schema"].schema] == [
        CONF_USERNAME,
        CONF_PASSWORD,
    ]


async def test_same_account_cannot_be_added_twice(hass):
    MockConfigEntry(domain=DOMAIN, unique_id="account:someuser").add_to_hass(hass)
    with patch(_LOGIN, new=AsyncMock(return_value=_TOKENS)):
        result = await _submit_account(hass, "SOMEUSER")
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (HermesAccountInvalidCredentials("x"), "invalid_auth"),
        (HermesAccountCompatibilityError("x"), "update_required"),
        (HermesAccountApiError("x"), "cannot_connect"),
    ],
)
async def test_account_login_failures_map_to_distinct_errors(hass, error, expected):
    with patch(_LOGIN, new=AsyncMock(side_effect=error)):
        result = await _submit_account(hass)
    assert result["type"] == "form"
    assert result["errors"] == {"base": expected}


async def test_account_blank_credentials_are_rejected_without_a_request(hass):
    with patch(_LOGIN, new=AsyncMock()) as login:
        result = await _submit_account(hass, username="  ", password="")
    assert result["errors"] == {"base": "invalid_auth"}
    login.assert_not_awaited()


def _account_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account:someuser",
        data={
            CONF_SOURCE: SOURCE_ACCOUNT,
            CONF_USERNAME: "someuser",
            "access_token": "old-a",
            "refresh_token": "old-r",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_reauth_asks_only_for_the_password_and_keeps_the_entry(hass):
    entry = _account_entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert [str(key) for key in result["data_schema"].schema] == [CONF_PASSWORD]
    assert result["description_placeholders"]["username"] == "someuser"

    with patch(_LOGIN, new=AsyncMock(return_value=_TOKENS)) as login, patch(
        "custom_components.hermes.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-pw"}
        )
        await hass.async_block_till_done()

    login.assert_awaited_once_with("someuser", "new-pw")
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.unique_id == "account:someuser"
    assert entry.data["access_token"] == "access-1"
    assert entry.data["refresh_token"] == "refresh-1"
    assert entry.data[CONF_USERNAME] == "someuser"
    assert CONF_PASSWORD not in entry.data


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (HermesAccountInvalidCredentials("x"), "invalid_auth"),
        (HermesAccountCompatibilityError("x"), "update_required"),
        (HermesAccountApiError("x"), "cannot_connect"),
    ],
)
async def test_reauth_wrong_password_stays_on_the_form(hass, error, expected):
    """A wrong password reaches reauth; a rejected key is a different error."""
    entry = _account_entry(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(_LOGIN, new=AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "nope"}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": expected}
    assert entry.data["access_token"] == "old-a"


async def test_account_options_menu_has_no_parcels_step(hass):
    entry = _account_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    assert result["menu_options"] == ["settings"]


async def test_entry_without_a_source_key_still_gets_the_parcels_step(hass):
    """Entries from before the account source have no source key at all."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == ["parcels", "settings"]


def _hub(parcels: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: parcels},
    )


def _init_input(
    *, add="", remove=None, history=False,
    filter_type="days", amount=7,
) -> dict:
    """Build the sectioned options-form submission."""
    parcels: dict = {"add": add}
    if remove is not None:
        parcels["remove"] = remove
    return {
        "parcels": parcels,
        "delivered": {
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        "history": {CONF_INCLUDE_HISTORY: history},
    }


async def _open_options_step(hass, entry, step_id: str):
    """Start the options flow and select one of its two top-level routes."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    assert result["menu_options"] == ["parcels", "settings"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )


async def test_options_parcel_list_can_be_cleared(hass):
    """A submitted empty list removes the final manually tracked parcel."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_PARCELS: [{CONF_TRACKING_CODE: "EXAMPLE111111"}]})
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": []}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == []


async def test_options_settings_preserve_parcel_list(hass):
    """Saving settings must never replace the manually tracked parcel list."""
    parcels = [{CONF_TRACKING_CODE: "EXAMPLE111111"}]
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_PARCELS: parcels})
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DELIVERED_FILTER_TYPE: "days", CONF_DELIVERED_FILTER_AMOUNT: 7, CONF_INCLUDE_HISTORY: False}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == parcels
