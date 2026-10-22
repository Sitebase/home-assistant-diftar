"""Fetch the collection calendar (ophaalkalender) from iok.be.

The Diftar portal links to iok.be for pickup dates. iok.be stores the chosen
address in the (anonymous) Drupal session and then offers the calendar as an
ICS download, so the address form is replayed: select the municipality, pick
the street, save, download.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import LOGGER

IOK_URL = "https://www.iok.be"
FORM_PATH = "/adres-kiezen?return=/afvalkalender"
AJAX_PATH = FORM_PATH + "&ajax_form=1&_wrapper_format=drupal_ajax"
DOWNLOAD_PATH = "/afvalkalender/download"
FORM_ID = "e2e_iok_address_form"
REQUEST_TIMEOUT = ClientTimeout(total=30)

# Codes used in the IOK calendar. GV and TEXT are not explained on the site;
# they are bulky waste and textile pickups.
FRACTIONS: dict[str, str] = {
    "RA": "Restafval",
    "GFT": "GFT",
    "PMD": "PMD",
    "P/K": "Papier / karton",
    "GV": "Grofvuil",
    "TEXT": "Textiel",
}

_BUILD_ID_RE = re.compile(r'name="form_build_id" value="([^"]+)"')
_OPTION_RE = re.compile(r'<option value="([^"]+)">')
_HOUSE_NUMBER_RE = re.compile(r"\s+\d+\s*[A-Za-z]?(?:\s*(?:bus|/)\s*\S+)?$", re.I)
_POSTCODE_RE = re.compile(r"^\d{4}\s+")


class IokError(Exception):
    """The calendar could not be fetched."""


class IokAddressError(IokError):
    """The municipality or street is not known to iok.be."""


@dataclass(slots=True, frozen=True)
class Pickup:
    """One pickup in the calendar."""

    day: date
    code: str

    @property
    def name(self) -> str:
        """Return the readable fraction name."""
        return FRACTIONS.get(self.code, self.code)


def split_address(street: str | None, city: str | None) -> tuple[str, str] | None:
    """Turn the portal address into the (municipality, street) iok.be expects.

    'Larumseweg 117' / '2440 Geel' becomes ('Geel', 'Larumseweg').
    """
    if not street or not city:
        return None
    street_name = _HOUSE_NUMBER_RE.sub("", street.strip())
    municipality = _POSTCODE_RE.sub("", city.strip())
    if not street_name or not municipality:
        return None
    return municipality, street_name


def parse_ics(text: str) -> list[Pickup]:
    """Parse the all-day events of the IOK calendar."""
    # Unfold continuation lines (RFC 5545 3.1).
    text = re.sub(r"\r?\n[ \t]", "", text)
    pickups: set[Pickup] = set()
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.split(";", 1)[0].upper()] = value.strip()
        summary, start = fields.get("SUMMARY"), fields.get("DTSTART", "")
        if not summary or len(start) < 8:
            continue
        try:
            day = datetime.strptime(start[:8], "%Y%m%d").date()
        except ValueError:
            continue
        pickups.add(Pickup(day=day, code=summary))
    return sorted(pickups, key=lambda pickup: (pickup.day, pickup.code))


class IokCalendarClient:
    """Download the collection calendar for one address.

    The session needs its own cookie jar: the address lives in the session.
    """

    def __init__(self, session: ClientSession, base_url: str = IOK_URL) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url

    async def _request(self, method: str, path: str, **kwargs: Any) -> str:
        try:
            async with self._session.request(
                method, self._base_url + path, timeout=REQUEST_TIMEOUT, **kwargs
            ) as response:
                if response.status >= 400:
                    raise IokError(f"Unexpected status {response.status} for {path}")
                return await response.text()
        except (ClientError, TimeoutError) as err:
            raise IokError(f"Error requesting {path}: {err}") from err

    async def _ajax(self, data: dict[str, str]) -> list[dict[str, Any]]:
        text = await self._request("POST", AJAX_PATH, data=data)
        try:
            commands = json.loads(text)
        except ValueError as err:
            raise IokError("Invalid response from the address form") from err
        if not isinstance(commands, list):
            raise IokError("Unexpected response from the address form")
        return commands

    @staticmethod
    def _new_build_id(commands: list[dict[str, Any]], current: str) -> str:
        for command in commands:
            if command.get("command") == "update_build_id" and command.get("new"):
                return str(command["new"])
        return current

    async def _match_street(self, municipality: str, street: str) -> str:
        """Return the street spelled exactly as iok.be knows it."""
        text = await self._request(
            "GET",
            f"/e2e-iok/address/getterms/iok_streets/"
            f"field_reference_iok_city.entity.name/{municipality}",
            params={"q": street},
        )
        try:
            options = [str(item["value"]) for item in json.loads(text)]
        except (ValueError, KeyError, TypeError) as err:
            raise IokError("Invalid street suggestions") from err
        for option in options:
            if option.casefold() == street.casefold():
                return option
        raise IokAddressError(f"Street {street!r} not found in {municipality}")

    async def async_get_municipalities(self) -> list[str]:
        """Return the municipalities served by IOK."""
        return _OPTION_RE.findall(await self._request("GET", FORM_PATH))

    async def async_get_pickups(self, municipality: str, street: str) -> list[Pickup]:
        """Select the address and download its calendar."""
        self._session.cookie_jar.clear()
        page = await self._request("GET", FORM_PATH)
        if f'<option value="{municipality}">' not in page:
            raise IokAddressError(f"Municipality {municipality!r} not served by IOK")
        build_id = _BUILD_ID_RE.search(page)
        if not build_id:
            raise IokError("Address form not found")
        form = {"form_build_id": build_id.group(1), "form_id": FORM_ID}

        # Each step rebuilds the Drupal form and hands out a new build id.
        commands = await self._ajax(
            {**form, "city": municipality, "_triggering_element_name": "city"}
        )
        form["form_build_id"] = self._new_build_id(commands, form["form_build_id"])
        street = await self._match_street(municipality, street)
        commands = await self._ajax(
            {
                **form,
                "city": municipality,
                "street": street,
                "_triggering_element_name": "street",
            }
        )
        form["form_build_id"] = self._new_build_id(commands, form["form_build_id"])
        await self._request(
            "POST",
            FORM_PATH,
            data={**form, "city": municipality, "street": street, "op": "Opslaan"},
        )

        text = await self._request("GET", DOWNLOAD_PATH)
        if "BEGIN:VCALENDAR" not in text:
            raise IokError("The calendar download did not return an ICS file")
        pickups = parse_ics(text)
        LOGGER.debug(
            "Fetched %s pickups for %s, %s", len(pickups), street, municipality
        )
        return pickups
