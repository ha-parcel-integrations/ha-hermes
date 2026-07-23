"""Hermes Germany Paket track-and-trace API client.

Talks to the keyless consumer endpoint the myhermes.de tracking widget uses.
The contract the coordinator relies on:

* ``async_get_parcel`` returns the raw per-parcel dict on success,
* returns ``None`` when the carrier says the tracking code is unknown or not
  yet scanned (a normal, expected state — never an error),
* raises :class:`HermesApiError` for anything else (a 5xx outage),
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)

# Sent to look like the myhermes.de tracking widget rather than a bare client.
# The endpoint is keyless, but a plausible UA + Referer avoids edge heuristics.
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "X-Language": "de",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"
    ),
    "Referer": "https://www.myhermes.de/",
}


class HermesApiError(Exception):
    """Raised when a Hermes API call returns an unexpected response."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Hermes API request failed: {detail}")
        self.detail = detail


class HermesApiClient:
    """Client for Hermes Germany's keyless Paket tracking endpoint.

    No authentication: the endpoint is keyed on the parcel number alone.
    Confirmed behaviour (``api.my-deliveries.de/tnt/v2/shipments/search/{n}``)::

        HTTP 200  → a JSON **array** of shipments; element 0 is the parcel
        HTTP 404  → number well-formed but not found / not yet scanned
        HTTP 400  → number malformed (bad format)

    404 / 400 / an empty array are all normal "no data yet" states → ``None``.
    See ``const.TRACKING_API_URL`` for the full endpoint notes.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the raw parcel dict (the first element of the response array),
        or ``None`` when the number is unknown / not yet scanned (404), badly
        formatted (400) or the array is empty. A 5xx (or any other non-2xx)
        raises :class:`HermesApiError`; network errors propagate as
        ``aiohttp.ClientError`` for the coordinator to wrap.
        """
        url = TRACKING_API_URL.format(tracking_code=tracking_code)
        async with self._session.get(url, headers=_REQUEST_HEADERS) as response:
            # 404 (unknown / not scanned) and 400 (malformed) are both normal
            # "no data yet" states here, not failures.
            if response.status in (400, 404):
                return None
            if response.status != 200:
                raise HermesApiError(f"HTTP {response.status}")
            try:
                # content_type=None: consumer endpoints routinely serve JSON as
                # text/plain, and aiohttp would otherwise refuse to parse it.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise HermesApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, list):
            raise HermesApiError("unexpected body (not a JSON array)")
        if not payload:
            # A 200 with an empty array is the same "nothing to show" state.
            return None
        parcel = payload[0]
        if not isinstance(parcel, dict):
            raise HermesApiError("unexpected array element (not a JSON object)")
        return parcel
