"""Tests for the Hermes API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.hermes.api import (
    HermesApiClient,
    HermesApiError,
)

CODE = "12345678901234"


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_first_array_element_on_success():
    """HTTP 200 is a JSON array; element 0 is the parcel."""
    parcel0 = {"barcode": CODE, "parcelProgress": [{"parcelStatus": "DELIVERED_HOMEDELIVERY"}]}
    session = _session_returning(200, [parcel0, {"barcode": "other"}])
    client = HermesApiClient(session)

    parcel = await client.async_get_parcel(CODE)

    assert parcel == parcel0
    # the tracking code ends up in the URL
    assert CODE in session.get.call_args[0][0]


async def test_get_parcel_returns_none_on_empty_array():
    """A 200 with an empty array is 'nothing to show yet'."""
    client = HermesApiClient(_session_returning(200, []))
    assert await client.async_get_parcel(CODE) is None


async def test_get_parcel_returns_none_on_404():
    """A well-formed but unknown / not-yet-scanned number 404s → None."""
    client = HermesApiClient(_session_returning(404, None))
    assert await client.async_get_parcel(CODE) is None


async def test_get_parcel_returns_none_on_400():
    """A malformed number 400s → None (bad format, treated as unknown)."""
    client = HermesApiClient(_session_returning(400, None))
    assert await client.async_get_parcel("000000000000") is None


async def test_get_parcel_raises_on_error_status():
    client = HermesApiClient(_session_returning(500, {}))
    with pytest.raises(HermesApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = HermesApiClient(_session_returning(200, "not json"))
    with pytest.raises(HermesApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_non_array_body():
    """A 200 that is not a JSON array is unexpected."""
    client = HermesApiClient(_session_returning(200, {"barcode": CODE}))
    with pytest.raises(HermesApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_non_object_array_element():
    client = HermesApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(HermesApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = HermesApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(CODE)
