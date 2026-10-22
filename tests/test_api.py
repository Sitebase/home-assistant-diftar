"""Tests for the mijndiftar.be client."""

from __future__ import annotations

from unittest.mock import patch

from aiohttp import CookieJar
import pytest

from custom_components.diftar.api import (
    DiftarAuthError,
    DiftarClient,
    DiftarConnectionError,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .conftest import PASSWORD, USERNAME, FakePortal


def _client(hass: HomeAssistant, password: str = PASSWORD) -> DiftarClient:
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    return DiftarClient(session, USERNAME, password)


async def test_fetch_all(hass: HomeAssistant, portal: FakePortal) -> None:
    """A full update reads every page."""
    data = await _client(hass).async_get_data()
    assert data.account.customer_number == "1234567"
    assert len(data.containers["1001"].collections) == 77
    assert len(data.containers["1002"].collections) == 9
    assert len(data.transactions) == 133
    assert data.balance == 35.09
    assert data.charts[0].image
    assert data.charts[0].content_type


async def test_pagination(hass: HomeAssistant, portal: FakePortal) -> None:
    """DataTables endpoints are read page by page."""
    with patch("custom_components.diftar.api.PAGE_SIZE", 20):
        data = await _client(hass).async_get_data()
    assert len(data.transactions) == 133
    assert len(data.containers["1001"].collections) == 77


async def test_relogin_between_select_and_fetch(
    hass: HomeAssistant, portal: FakePortal
) -> None:
    """A new session after selecting a container repeats the selection."""
    portal.expire_after_select = True
    data = await _client(hass).async_get_data()
    assert portal.logins == 2
    # Without the retry the fallback (paper) data would be booked here.
    assert len(data.containers["1001"].collections) == 77


async def test_invalid_auth(hass: HomeAssistant, portal: FakePortal) -> None:
    """A rejected login raises an auth error."""
    with pytest.raises(DiftarAuthError, match="niet gevonden"):
        await _client(hass, "wrong").async_get_account_id()


async def test_unexpected_login_response(
    hass: HomeAssistant, portal: FakePortal
) -> None:
    """A login answer that is neither a redirect nor the form is a connection error."""
    portal.login_response = "<html>maintenance</html>"
    with pytest.raises(DiftarConnectionError, match="Unexpected login response"):
        await _client(hass).async_get_account_id()


async def test_layout_change_is_logged(
    hass: HomeAssistant, portal: FakePortal, caplog: pytest.LogCaptureFixture
) -> None:
    """Pages without containers or balance log a warning once."""
    portal.overrides["/Aansluitpunten/Verrichtingen"] = "<html></html>"
    client = _client(hass)
    data = await client.async_get_data()
    await client.async_get_data()
    assert data.balance is None
    assert caplog.text.count("portal layout may have changed") == 1
