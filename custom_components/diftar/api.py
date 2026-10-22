"""Async client for the mijndiftar.be customer portal."""

from __future__ import annotations

import asyncio
from datetime import tzinfo
import json
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from . import parser
from .const import BASE_URL, LOGGER, TIMEZONE
from .models import Container, DiftarData

LOGIN_PATH = "/Account/LogOn"
PAGE_SIZE = 500
CONTAINER_ATTEMPTS = 2
REQUEST_TIMEOUT = ClientTimeout(total=30)


class DiftarError(Exception):
    """Base error for the Diftar client."""


class DiftarConnectionError(DiftarError):
    """The portal could not be reached or returned something unexpected."""


class DiftarAuthError(DiftarError):
    """The username or password was rejected."""


class DiftarClient:
    """Scrape a single mijndiftar.be account.

    The portal keeps the selected container in the server side session, so
    requests for one account must run sequentially. The session must have its
    own cookie jar: never share it with other integrations.
    """

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        base_url: str = BASE_URL,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._username = username
        self._password = password
        self._base_url = base_url
        self._tz: tzinfo = ZoneInfo(TIMEZONE)
        self._lock = asyncio.Lock()
        self._logged_in = False
        self._logins = 0
        self._layout_warned = False

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> tuple[ClientResponse, bytes]:
        url = path if path.startswith("http") else self._base_url + path
        try:
            async with self._session.request(
                method, url, timeout=REQUEST_TIMEOUT, **kwargs
            ) as response:
                body = await response.read()
        except (ClientError, TimeoutError) as err:
            raise DiftarConnectionError(f"Error requesting {path}: {err}") from err
        if response.status >= 400:
            raise DiftarConnectionError(
                f"Unexpected status {response.status} for {path}"
            )
        return response, body

    async def login(self) -> None:
        """Log in with username and password."""
        self._logged_in = False
        self._session.cookie_jar.clear()
        # Fetch the form first so the portal hands out a session cookie.
        await self._request("GET", LOGIN_PATH)
        response, body = await self._request(
            "POST",
            LOGIN_PATH,
            data={
                "Identifier": self._username,
                "AuthenticationValue": self._password,
                "RememberMe": "false",
                "LogonByName": "aanmelden",
            },
            allow_redirects=False,
        )
        location = response.headers.get("Location", "")
        if response.status in (301, 302, 303) and "logon" not in location.lower():
            self._logged_in = True
            self._logins += 1
            return
        page = body.decode("utf-8", "replace")
        if parser.is_login_page(page):
            message = parser.login_error(page)
            LOGGER.debug("Login rejected: %s", message)
            raise DiftarAuthError(message or "Login failed")
        raise DiftarConnectionError(f"Unexpected login response {response.status}")

    async def _get(self, path: str, **kwargs: Any) -> str:
        """GET an authenticated page, logging in again when the session expired."""
        if not self._logged_in:
            await self.login()
        for attempt in range(2):
            response, body = await self._request("GET", path, **kwargs)
            text = body.decode("utf-8", "replace")
            expired = "/account/logon" in str(response.url).lower() or (
                parser.is_login_page(text) and not path.startswith(LOGIN_PATH)
            )
            if not expired:
                return text
            if attempt == 0:
                LOGGER.debug("Session expired while fetching %s, logging in", path)
                await self.login()
        raise DiftarAuthError("Session was rejected after logging in again")

    async def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a DataTables JSON endpoint."""
        text = await self._get(path, params=params)
        try:
            data = json.loads(text)
        except ValueError as err:
            raise DiftarConnectionError(f"Invalid JSON from {path}") from err
        if not isinstance(data, dict):
            raise DiftarConnectionError(f"Unexpected JSON from {path}")
        return data

    async def _get_rows(self, path: str, extra: dict[str, str]) -> list[list[Any]]:
        """Fetch all pages of a DataTables server side endpoint."""
        rows: list[list[Any]] = []
        start = 0
        while True:
            data = await self._get_json(
                path,
                {
                    "sEcho": "1",
                    "sSearchFilter": "[]",
                    "DisplayStart": str(start),
                    "DisplayLength": str(PAGE_SIZE),
                    "SearchQuery": "",
                    "SortBy": "",
                    "SortDirection": "",
                    **extra,
                },
            )
            page = data.get("aaData") or []
            rows.extend(page)
            total = int(data.get("iTotalDisplayRecords") or 0)
            start += len(page)
            if not page or start >= total:
                return rows

    async def _fetch_container_details(self, container: Container) -> None:
        # Opening the detail page selects the container in the session; the
        # JSON endpoint then returns the collections of that container. A new
        # login in between starts a fresh session without a selection, so the
        # pair is repeated rather than booking another container's data.
        for _ in range(CONTAINER_ATTEMPTS):
            logins = self._logins
            await self._get(f"/Aansluitpunten/Inzamelingen/{container.container_id}")
            rows = await self._get_rows(
                "/Aansluitpunten/ShowResultsInzamelingen",
                {
                    "Criteria.IsGefiltered": "False",
                    "Criteria.DatumVanString": "",
                    "Criteria.DatumTotString": "",
                },
            )
            if self._logins == logins:
                break
        else:
            raise DiftarConnectionError(
                f"Session kept expiring while reading container {container.container_id}"
            )
        container.collections = parser.parse_collections(rows, self._tz)
        page = await self._get(f"/Aansluitpunten/Interventies/{container.container_id}")
        container.interventions = parser.count_table_rows(page)

    async def async_get_account_id(self) -> str:
        """Log in and return the customer number, used as unique id."""
        async with self._lock:
            await self.login()
            page = await self._get("/Aansluitpunten/Containers")
        try:
            return parser.parse_account(page).customer_number
        except ValueError as err:
            raise DiftarConnectionError(str(err)) from err

    async def async_get_data(self) -> DiftarData:
        """Fetch everything from the account."""
        async with self._lock:
            return await self._fetch_all()

    async def _fetch_all(self) -> DiftarData:
        page = await self._get("/Aansluitpunten/Containers")
        try:
            account = parser.parse_account(page)
        except ValueError as err:
            raise DiftarConnectionError(str(err)) from err
        data = DiftarData(account=account)

        containers = parser.parse_containers(page)
        for container in containers:
            await self._fetch_container_details(container)
            data.containers[container.container_id] = container

        page = await self._get("/Aansluitpunten/Verrichtingen")
        data.balance = parser.parse_balance(page)
        if not containers or data.balance is None:
            self._warn_layout(containers=len(containers), balance=data.balance)
        data.transactions = parser.parse_transactions(
            await self._get_rows(
                "/Aansluitpunten/ShowResultsVerrichtingen", {"Verrichtingtypeid": ""}
            )
        )

        page = await self._get("/Aansluitpunten/Betalingsuitnodigingen")
        data.payment_invitations = parser.parse_payment_invitations(page)
        data.messages = parser.count_table_rows(
            await self._get("/Aansluitpunten/Berichten")
        )
        data.on_demand_pickups = parser.count_table_rows(
            await self._get("/Aansluitpunten/Ophalingen")
        )
        data.extra_bags = parser.count_table_rows(
            await self._get("/Aansluitpunten/ExtraZakken")
        )

        page = await self._get("/Aansluitpunten/Statistieken")
        data.charts = parser.parse_charts(page, self._base_url)
        for chart in data.charts:
            try:
                response, chart.image = await self._request("GET", chart.url)
            except DiftarConnectionError as err:
                LOGGER.debug("Could not fetch statistics chart: %s", err)
                continue
            chart.content_type = response.content_type or chart.content_type
        return data

    def _warn_layout(self, **found: Any) -> None:
        """Warn once when pages parse to nothing, the portal layout may have changed."""
        if self._layout_warned:
            return
        self._layout_warned = True
        LOGGER.warning(
            "mijndiftar.be returned pages without the expected data (%s); the "
            "portal layout may have changed, please open an issue",
            ", ".join(f"{key}={value}" for key, value in found.items()),
        )
