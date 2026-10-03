"""Minimal client for the Hermes account inbox.

Isolated from the keyless tracking client: it uses a user-owned token pair and
transport values from ``const.py``. Responses come back as raw dictionaries;
normalisation belongs in ``parcels.py``.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from ..const import (
    ACCOUNT_API_KEY,
    ACCOUNT_API_URL,
    ACCOUNT_APP_VERSION,
)

TokenCallback = Callable[[dict[str, Any]], Awaitable[None]]

_LOGIN_PATH = "users/login"
_REFRESH_PATH = "users/refreshtoken"
_SHIPMENTS_PATH = "shipments"


class HermesAccountApiError(Exception):
    """An unexpected account API response, without sensitive response data."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        """Store safe failure metadata without retaining the response body."""
        super().__init__(detail)
        self.status_code = status_code


class HermesAccountInvalidCredentials(HermesAccountApiError):
    """The supplied username/password was rejected."""


class HermesAccountReauthRequired(HermesAccountApiError):
    """Stored user tokens cannot be refreshed."""


class HermesAccountCompatibilityError(HermesAccountApiError):
    """The gateway refused the app credentials; the integration needs an update."""


def _is_html(content_type: str | None, body: str) -> bool:
    """Whether a rejection came from the gateway rather than the login service.

    The gateway answers with a tiny ``text/html`` page before it ever looks at
    the user's credentials; the login service itself answers in JSON.
    """
    if content_type and "html" in content_type.lower():
        return True
    return body.lstrip().startswith("<")


def _tokens(payload: Any) -> dict[str, Any]:
    """Extract the only token fields persisted by the integration."""
    if not isinstance(payload, dict):
        raise HermesAccountApiError("missing login response")
    access_token = payload.get("accessToken")
    refresh_token = payload.get("refreshToken")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise HermesAccountApiError("missing account tokens")
    return {"access_token": access_token, "refresh_token": refresh_token}


class HermesAccountClient:
    """Hermes account API client with Bearer authorisation."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_callback: TokenCallback | None = None,
    ) -> None:
        """Initialise the client with entry-owned tokens and persistence hook."""
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_callback = token_callback

    def _headers(self, *, include_auth: bool = True) -> dict[str, str]:
        """Build the mobile API headers."""
        headers = {
            "api-key": ACCOUNT_API_KEY,
            "user-agent": f"Hermes - ios - {ACCOUNT_APP_VERSION}",
            "accept-language": "de-de",
            "accept": "application/json",
        }
        if include_auth and self._access_token:
            headers["authorization"] = f"Bearer {self._access_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        include_auth: bool = True,
    ) -> Any:
        headers = self._headers(include_auth=include_auth)
        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            headers["content-type"] = "application/json"
            kwargs["json"] = body
        try:
            async with self._session.request(
                method, f"{ACCOUNT_API_URL}/{path}", **kwargs
            ) as response:
                if response.status in (401, 403):
                    text = await response.text()
                    # The gateway refuses a rejected app key with an HTML 403
                    # before it checks the password, so the body — not just the
                    # status — decides whether this is the user's problem.
                    if _is_html(response.content_type, text):
                        raise HermesAccountCompatibilityError(
                            "account API rejected app compatibility",
                            status_code=response.status,
                        )
                    if path == _LOGIN_PATH:
                        raise HermesAccountInvalidCredentials(
                            "login rejected", status_code=response.status
                        )
                    raise HermesAccountReauthRequired(
                        "account token rejected", status_code=response.status
                    )
                if response.status != 200:
                    raise HermesAccountApiError(
                        "account API request failed", status_code=response.status
                    )
                try:
                    return await response.json(content_type=None)
                except ValueError as err:
                    raise HermesAccountApiError(
                        "account API returned invalid JSON"
                    ) from err
        except aiohttp.ClientError as err:
            raise HermesAccountApiError("account API unreachable") from err

    async def async_login(self, username: str, password: str) -> dict[str, Any]:
        """Authenticate once; callers persist only the returned token pair."""
        tokens = _tokens(
            await self._request(
                "POST",
                _LOGIN_PATH,
                body={"username": username, "password": password},
                include_auth=False,
            )
        )
        self._access_token = tokens["access_token"]
        self._refresh_token = tokens["refresh_token"]
        return tokens

    async def async_refresh(self) -> dict[str, Any]:
        """Rotate the stored token pair once and notify the entry owner."""
        if not self._refresh_token:
            raise HermesAccountReauthRequired("no refresh token")
        tokens = _tokens(
            await self._request(
                "POST",
                _REFRESH_PATH,
                body={"refreshToken": self._refresh_token},
                include_auth=False,
            )
        )
        self._access_token = tokens["access_token"]
        self._refresh_token = tokens["refresh_token"]
        if self._token_callback:
            await self._token_callback(tokens)
        return tokens

    async def async_get_shipments(self) -> list[dict[str, Any]]:
        """Return the account's shipments; an empty account is ``[]``."""
        try:
            payload = await self._request("GET", _SHIPMENTS_PATH)
        except HermesAccountReauthRequired:
            # A token can expire between polls. Rotate once, then retry the
            # read exactly once; a second rejection starts HA reauth.
            await self.async_refresh()
            payload = await self._request("GET", _SHIPMENTS_PATH)
        if not isinstance(payload, list):
            raise HermesAccountApiError("unexpected shipments response")
        return [item for item in payload if isinstance(item, dict)]
