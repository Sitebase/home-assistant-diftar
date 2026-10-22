"""Tests for the iok.be collection calendar."""

from __future__ import annotations

from datetime import date

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.diftar.const import (
    CALENDAR_UPDATE_INTERVAL,
    CONF_MUNICIPALITY,
    CONF_STREET,
    DOMAIN,
)
from custom_components.diftar.iok import Pickup, parse_ics, split_address
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from .conftest import CUSTOMER_NUMBER, FakeIok, FakePortal, load_fixture

C = CUSTOMER_NUMBER


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time on the first day of the calendar fixture."""
    freezer.move_to("2026-10-22T12:00:00+02:00")
    return freezer


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, unique_id: str, domain: str = "sensor") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, unique_id
    return entity_id


def test_split_address() -> None:
    """House number and postcode are dropped."""
    assert split_address("Larumseweg 117", "2440 Geel") == ("Geel", "Larumseweg")
    assert split_address("Kerkstraat 12 bus 3", "2400 Mol") == ("Mol", "Kerkstraat")
    assert split_address("Markt 1A", "2440 Geel") == ("Geel", "Markt")
    assert split_address(None, "2440 Geel") is None


def test_parse_ics() -> None:
    """All-day events are parsed, sorted and deduplicated."""
    pickups = parse_ics(load_fixture("iok_calendar.ics"))
    assert len(pickups) == 21
    assert pickups[0] == Pickup(day=date(2026, 10, 22), code="GFT")
    assert {pickup.code for pickup in pickups} == {
        "GFT",
        "RA",
        "PMD",
        "GV",
        "P/K",
        "TEXT",
    }
    assert Pickup(day=date(2026, 10, 29), code="RA").name == "Restafval"


async def test_calendar_and_next_pickups(
    hass: HomeAssistant,
    portal: FakePortal,
    iok: FakeIok,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The address from the portal is used and the calendar is exposed."""
    await _setup(hass, mock_config_entry)
    assert iok.saved == ("Geel", "Kerkstraat")

    calendar = hass.states.get(_entity_id(hass, f"{C}_collection_calendar", "calendar"))
    assert calendar.state == "on"  # GFT today
    assert calendar.attributes["message"] == "GFT"

    state = hass.states.get(_entity_id(hass, f"{C}_next_pickup"))
    assert state.state == "2026-10-22"
    assert state.attributes["fractions"] == ["GFT"]
    restafval = hass.states.get(_entity_id(hass, f"{C}_next_pickup_ra"))
    assert restafval.state == "2026-10-29"
    assert restafval.attributes["days_until"] == 7

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar.entity_id,
            "start_date_time": "2026-11-01T00:00:00+01:00",
            "end_date_time": "2026-11-07T00:00:00+01:00",
        },
        blocking=True,
        return_response=True,
    )
    events = result[calendar.entity_id]["events"]
    assert [(e["start"], e["summary"]) for e in events] == [
        ("2026-11-02", "Grofvuil"),
        ("2026-11-05", "GFT"),
        ("2026-11-05", "Papier / karton"),
    ]


async def test_calendar_is_downloaded_once(
    hass: HomeAssistant,
    portal: FakePortal,
    iok: FakeIok,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """The ICS is cached: daily checks and reloads do not download again."""
    await _setup(hass, mock_config_entry)
    assert iok.downloads == 1

    for _ in range(3):
        frozen_time.tick(CALENDAR_UPDATE_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert iok.downloads == 1

    # The next pickup moves on at midnight without a download.
    assert hass.states.get(_entity_id(hass, f"{C}_next_pickup")).state != "2026-10-22"


async def test_calendar_refreshes_when_running_out(
    hass: HomeAssistant,
    portal: FakePortal,
    iok: FakeIok,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """In December the calendar is fetched again, at most once a day."""
    await _setup(hass, mock_config_entry)
    frozen_time.move_to("2026-12-05T12:00:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert iok.downloads == 2

    await mock_config_entry.runtime_data.calendar.async_refresh()
    assert iok.downloads == 2

    # A failing download keeps the stored calendar.
    iok.down = True
    frozen_time.move_to("2026-12-06T12:00:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(_entity_id(hass, f"{C}_next_pickup")).state != (
        STATE_UNAVAILABLE
    )


async def test_calendar_failure_does_not_block_setup(
    hass: HomeAssistant,
    portal: FakePortal,
    iok: FakeIok,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Without iok.be only the calendar entities are unavailable."""
    iok.down = True
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    calendar = _entity_id(hass, f"{C}_collection_calendar", "calendar")
    assert hass.states.get(calendar).state == STATE_UNAVAILABLE
    assert hass.states.get(_entity_id(hass, f"{C}_balance")).state == "35.09"


async def test_options_change_address(
    hass: HomeAssistant,
    portal: FakePortal,
    iok: FakeIok,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The calendar address can be overridden and is validated."""
    await _setup(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MUNICIPALITY: "Geel", CONF_STREET: "Onbekend"}
    )
    assert result["errors"] == {CONF_STREET: "address_not_found"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MUNICIPALITY: "Geel", CONF_STREET: " Larumseweg "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert mock_config_entry.options == {
        CONF_MUNICIPALITY: "Geel",
        CONF_STREET: "Larumseweg",
    }
    assert iok.saved == ("Geel", "Larumseweg")
    assert mock_config_entry.runtime_data.calendar.address == ("Geel", "Larumseweg")
