"""Tests for the account client: login, refresh, and the 403 branching."""
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.hermes.account.client import (
    HermesAccountApiError,
    HermesAccountClient,
    HermesAccountCompatibilityError,
    HermesAccountInvalidCredentials,
    HermesAccountReauthRequired,
)
from custom_components.hermes.const import ACCOUNT_API_KEY, ACCOUNT_API_URL

# What the gateway sends when it refuses the app credentials.
GATEWAY_403 = "<html><head><title>403</title></head><body>403 Forbidden</body></html>"
TOKENS = {"accessToken": "access-1", "refreshToken": "refresh-1"}


class _Response:
    def __init__(
        self,
        status=200,
        payload=None,
        *,
        text="",
        content_type="application/json",
        invalid_json=False,
    ):
        self.status = status
        self.content_type = content_type
        self._payload = payload
        self._text = text
        self._invalid_json = invalid_json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, **kwargs):
        if self._invalid_json:
            raise ValueError
        return self._payload

    async def text(self):
        return self._text


def _client(*responses, **kwargs):
    session = MagicMock()
    session.request.side_effect = list(responses)
    return HermesAccountClient(session, **kwargs), session


async def test_login_sends_username_and_keeps_only_the_token_pair():
    client, session = _client(_Response(200, {**TOKENS, "unrelated": "x"}))

    tokens = await client.async_login("someone", "pw")

    assert tokens == {"access_token": "access-1", "refresh_token": "refresh-1"}
    method, url = session.request.call_args.args
    assert (method, url) == ("POST", f"{ACCOUNT_API_URL}/users/login")
    kwargs = session.request.call_args.kwargs
    assert kwargs["json"] == {"username": "someone", "password": "pw"}
    assert kwargs["headers"]["api-key"] == ACCOUNT_API_KEY
    assert kwargs["headers"]["accept-language"] == "de-de"
    assert kwargs["headers"]["user-agent"].startswith("Hermes - ios - ")
    assert "authorization" not in kwargs["headers"]


async def test_login_without_tokens_is_an_api_error():
    client, _ = _client(_Response(200, {"accessToken": "only-one"}))
    with pytest.raises(HermesAccountApiError):
        await client.async_login("someone", "pw")
    client, _ = _client(_Response(200, ["not", "a", "dict"]))
    with pytest.raises(HermesAccountApiError):
        await client.async_login("someone", "pw")


async def test_shipments_request_carries_bearer_and_returns_the_array():
    client, session = _client(
        _Response(200, [{"barcode": "A"}, "junk", {"barcode": "B"}]),
        access_token="access-1",
    )

    assert await client.async_get_shipments() == [{"barcode": "A"}, {"barcode": "B"}]

    method, url = session.request.call_args.args
    assert (method, url) == ("GET", f"{ACCOUNT_API_URL}/shipments")
    headers = session.request.call_args.kwargs["headers"]
    assert headers["authorization"] == "Bearer access-1"
    assert headers["api-key"] == ACCOUNT_API_KEY
    assert "json" not in session.request.call_args.kwargs


async def test_empty_account_is_an_empty_list():
    client, _ = _client(_Response(200, []), access_token="a")
    assert await client.async_get_shipments() == []


async def test_non_array_shipments_body_is_an_api_error():
    client, _ = _client(_Response(200, {"shipments": []}), access_token="a")
    with pytest.raises(HermesAccountApiError):
        await client.async_get_shipments()


async def test_html_403_on_login_is_a_compatibility_failure_not_bad_credentials():
    """The gateway refuses a rejected app key before it checks the password."""
    client, _ = _client(
        _Response(403, text=GATEWAY_403, content_type="text/html")
    )
    with pytest.raises(HermesAccountCompatibilityError) as caught:
        await client.async_login("someone", "pw")
    assert not isinstance(caught.value, HermesAccountInvalidCredentials)
    assert caught.value.status_code == 403


async def test_html_body_is_enough_even_without_an_html_content_type():
    client, _ = _client(_Response(403, text=GATEWAY_403, content_type="application/json"))
    with pytest.raises(HermesAccountCompatibilityError):
        await client.async_login("someone", "pw")


@pytest.mark.parametrize("status", [401, 403])
async def test_json_rejection_on_login_is_bad_credentials(status):
    client, _ = _client(
        _Response(status, text='{"error": "bad credentials"}')
    )
    with pytest.raises(HermesAccountInvalidCredentials):
        await client.async_login("someone", "wrong")


async def test_empty_body_rejection_on_login_is_bad_credentials():
    client, _ = _client(_Response(401, text=""))
    with pytest.raises(HermesAccountInvalidCredentials):
        await client.async_login("someone", "wrong")


async def test_html_403_on_the_inbox_is_compatibility_not_reauth():
    client, _ = _client(
        _Response(403, text=GATEWAY_403, content_type="text/html"),
        access_token="a",
        refresh_token="r",
    )
    with pytest.raises(HermesAccountCompatibilityError):
        await client.async_get_shipments()


async def test_expired_token_is_refreshed_and_the_read_retried_once():
    callback = AsyncMock()
    client, session = _client(
        _Response(401, text='{"error": "expired"}'),
        _Response(200, {"accessToken": "access-2", "refreshToken": "refresh-2"}),
        _Response(200, [{"barcode": "A"}]),
        access_token="access-1",
        refresh_token="refresh-1",
        token_callback=callback,
    )

    assert await client.async_get_shipments() == [{"barcode": "A"}]

    callback.assert_awaited_once_with(
        {"access_token": "access-2", "refresh_token": "refresh-2"}
    )
    refresh_call = session.request.call_args_list[1]
    assert refresh_call.args[1] == f"{ACCOUNT_API_URL}/users/refreshtoken"
    assert refresh_call.kwargs["json"] == {"refreshToken": "refresh-1"}
    assert "authorization" not in refresh_call.kwargs["headers"]
    retry = session.request.call_args_list[2]
    assert retry.kwargs["headers"]["authorization"] == "Bearer access-2"


async def test_second_rejection_after_refresh_requires_reauth():
    client, _ = _client(
        _Response(401, text="{}"),
        _Response(200, {"accessToken": "access-2", "refreshToken": "refresh-2"}),
        _Response(401, text="{}"),
        access_token="a",
        refresh_token="r",
    )
    with pytest.raises(HermesAccountReauthRequired):
        await client.async_get_shipments()


async def test_rejected_refresh_token_requires_reauth():
    client, _ = _client(
        _Response(401, text="{}"),
        _Response(401, text='{"error": "refresh token expired"}'),
        access_token="a",
        refresh_token="r",
    )
    with pytest.raises(HermesAccountReauthRequired):
        await client.async_get_shipments()


async def test_refresh_without_a_token_requires_reauth():
    client, session = _client()
    with pytest.raises(HermesAccountReauthRequired):
        await client.async_refresh()
    session.request.assert_not_called()


async def test_refresh_without_a_callback_still_rotates_the_tokens():
    client, _ = _client(
        _Response(200, {"accessToken": "access-2", "refreshToken": "refresh-2"}),
        refresh_token="r",
    )
    assert await client.async_refresh() == {
        "access_token": "access-2",
        "refresh_token": "refresh-2",
    }


async def test_other_statuses_are_api_errors_with_the_code():
    client, _ = _client(_Response(500), access_token="a")
    with pytest.raises(HermesAccountApiError) as caught:
        await client.async_get_shipments()
    assert caught.value.status_code == 500


async def test_invalid_json_is_an_api_error():
    client, _ = _client(_Response(200, invalid_json=True), access_token="a")
    with pytest.raises(HermesAccountApiError):
        await client.async_get_shipments()


async def test_network_failure_is_an_api_error():
    session = MagicMock()
    session.request.side_effect = aiohttp.ClientConnectionError("down")
    client = HermesAccountClient(session, access_token="a")
    with pytest.raises(HermesAccountApiError):
        await client.async_get_shipments()
