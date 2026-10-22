"""Fixtures for the Diftar tests."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.diftar.const import BASE_URL, DOMAIN
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import device_registry as dr

FIXTURES = Path(__file__).parent / "fixtures"
USERNAME = "jan"
PASSWORD = "secret"
CUSTOMER_NUMBER = "1234567"


def load_fixture(name: str) -> str:
    """Load a text fixture."""
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakePortal:
    """Simulate the session based mijndiftar.be portal."""

    def __init__(self) -> None:
        """Initialize the portal."""
        self.logged_in = False
        self.selected: str | None = None
        self.password = PASSWORD
        self.logins = 0
        self.down = False
        # Drop the session right after a container was selected.
        self.expire_after_select = False
        self.login_response: str | None = None
        self.overrides: dict[str, str] = {}
        self.pages = {
            "/Aansluitpunten/Containers": "containers.html",
            "/Aansluitpunten/Verrichtingen": "verrichtingen.html",
            "/Aansluitpunten/Betalingsuitnodigingen": "betalingsuitnodigingen.html",
            "/Aansluitpunten/Berichten": "berichten.html",
            "/Aansluitpunten/Ophalingen": "ophalingen.html",
            "/Aansluitpunten/ExtraZakken": "extrazakken.html",
            "/Aansluitpunten/Statistieken": "statistieken.html",
            "/Aansluitpunten/ShowResultsVerrichtingen": "verrichtingen.json",
        }

    def _response(
        self, method: str, url: URL, status: int = 200, **kwargs: Any
    ) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, status=status, **kwargs)

    def _paged(self, method: str, url: URL, name: str) -> AiohttpClientMockResponse:
        """Serve a DataTables endpoint, honouring DisplayStart/DisplayLength."""
        data = json.loads(load_fixture(name))
        start = int(url.query.get("DisplayStart", 0))
        length = int(url.query.get("DisplayLength", 10))
        data["aaData"] = data["aaData"][start : start + length]
        return self._response(method, url, json=data)

    async def __call__(  # noqa: PLR0911, PLR0912
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        """Answer a request."""
        if self.down:
            return self._response(method, url, status=503)
        path = url.path
        if path == "/Account/LogOn":
            if method.lower() == "get":
                return self._response(method, url, text=load_fixture("logon.html"))
            if self.login_response is not None:
                return self._response(method, url, text=self.login_response)
            if data["Identifier"] == USERNAME and data["AuthenticationValue"] == (
                self.password
            ):
                self.logged_in = True
                self.logins += 1
                return self._response(
                    method, url, status=302, headers={"Location": "/Aansluitpunten"}
                )
            return self._response(method, url, text=load_fixture("logon_failed.html"))

        if not self.logged_in:
            # The real portal redirects to the login form.
            return self._response(
                method,
                URL(f"{BASE_URL}/Account/Logon"),
                text=load_fixture("logon.html"),
            )
        if path.startswith("/Statistiek/"):
            return self._response(
                method, url, response=(FIXTURES / "chart.png").read_bytes()
            )
        if match := re.match(r"/Aansluitpunten/Inzamelingen/(\d+)", path):
            self.selected = match.group(1)
            if self.expire_after_select:
                self.expire_after_select = False
                self.logged_in = False
                self.selected = None
            return self._response(method, url, text="<html></html>")
        if path.startswith("/Aansluitpunten/Interventies/"):
            return self._response(method, url, text=load_fixture("interventies.html"))
        if path == "/Aansluitpunten/ShowResultsInzamelingen":
            # Without a selection the portal falls back to another container.
            name = {"1001": "inzamelingen_restafval.json"}.get(
                self.selected or "", "inzamelingen_papier.json"
            )
            return self._paged(method, url, name)
        if path.startswith("/Aansluitpunten/ShowResults"):
            return self._paged(method, url, self.pages[path])
        if path in self.overrides:
            return self._response(method, url, text=self.overrides[path])
        if path in self.pages:
            return self._response(method, url, text=load_fixture(self.pages[path]))
        return self._response(method, url, status=404)


class FakeIok:
    """Simulate the iok.be address form and calendar download."""

    def __init__(self) -> None:
        """Initialize the site."""
        self.streets = {"Geel": ["Kerkstraat", "Larumseweg"]}
        self.saved: tuple[str, str] | None = None
        self.downloads = 0
        self.down = False

    async def __call__(  # noqa: PLR0911
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        """Answer a request."""
        if self.down:
            return AiohttpClientMockResponse(method, url, status=503)
        path, data = url.path, data or {}
        if path == "/adres-kiezen" and "ajax_form" in url.query:
            name = (
                "iok_ajax_city.json"
                if data.get("_triggering_element_name") == "city"
                else "iok_ajax_street.json"
            )
            return AiohttpClientMockResponse(method, url, text=load_fixture(name))
        if path == "/adres-kiezen" and method.lower() == "post":
            if data.get("street") in self.streets.get(data.get("city"), []):
                self.saved = (data["city"], data["street"])
            return AiohttpClientMockResponse(method, url, text="<html></html>")
        if path == "/adres-kiezen":
            return AiohttpClientMockResponse(
                method, url, text=load_fixture("iok_form.html")
            )
        if path.startswith("/e2e-iok/address/getterms/"):
            city = path.rsplit("/", 1)[1]
            query = url.query.get("q", "").casefold()
            matches = [
                {"value": street, "label": street}
                for street in self.streets.get(city, [])
                if street.casefold().startswith(query)
            ]
            return AiohttpClientMockResponse(method, url, json=matches)
        if path == "/afvalkalender/download" and self.saved:
            self.downloads += 1
            return AiohttpClientMockResponse(
                method, url, text=load_fixture("iok_calendar.ics")
            )
        return AiohttpClientMockResponse(method, url, text="<html></html>")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


@pytest.fixture(autouse=True)
async def brussels_time_zone(hass) -> None:
    """Run the tests in the time zone of the portal."""
    await hass.config.async_set_time_zone("Europe/Brussels")


def get_device(hass, identifier: str, entry: MockConfigEntry):
    """Look up a device of the entry across Home Assistant versions."""
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(
            (DOMAIN, identifier), entry.entry_id
        )
    return registry.async_get_device({(DOMAIN, identifier)})


@pytest.fixture
def portal(aioclient_mock: AiohttpClientMocker) -> FakePortal:
    """Register the fake portal for every request to mijndiftar.be."""
    fake = FakePortal()
    for method in ("get", "post"):
        aioclient_mock.request(
            method, re.compile(r"^https://www\.mijndiftar\.be/"), side_effect=fake
        )
    return fake


@pytest.fixture(autouse=True)
def iok(aioclient_mock: AiohttpClientMocker) -> FakeIok:
    """Register the fake iok.be site."""
    fake = FakeIok()
    for method in ("get", "post"):
        aioclient_mock.request(
            method, re.compile(r"^https://www\.iok\.be/"), side_effect=fake
        )
    return fake


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Diftar {CUSTOMER_NUMBER}",
        unique_id=CUSTOMER_NUMBER,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )


@pytest.fixture
def mock_setup_entry() -> Generator[None]:
    """Skip setting up the integration in config flow tests."""
    with patch("custom_components.diftar.async_setup_entry", return_value=True):
        yield
