"""Tests for entity behaviour over time."""

from __future__ import annotations

from http import HTTPStatus
import re

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.diftar import async_remove_config_entry_device
from custom_components.diftar.const import DOMAIN, UPDATE_INTERVAL
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import CUSTOMER_NUMBER, FakePortal, get_device, load_fixture

C = CUSTOMER_NUMBER


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, unique_id: str, domain: str = "sensor") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, unique_id
    return entity_id


async def _refresh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time after the last fixture collection."""
    freezer.move_to("2026-10-22T12:00:00+02:00")
    return freezer


async def test_yearly_sensors_have_last_reset(
    hass: HomeAssistant, portal: FakePortal, mock_config_entry: MockConfigEntry
) -> None:
    """Yearly totals reset at the start of the local year."""
    await _setup(hass, mock_config_entry)
    for unique_id in (
        f"{C}_costs_this_year",
        f"{C}_1001_weight_this_year",
        f"{C}_1001_collections_this_year",
        f"{C}_1001_costs_this_year",
    ):
        state = hass.states.get(_entity_id(hass, unique_id))
        assert state.attributes["state_class"] == "total"
        assert state.attributes["last_reset"] == "2026-01-01T00:00:00+01:00"


async def test_diagnostic_counters_disabled_by_default(
    hass: HomeAssistant, portal: FakePortal, mock_config_entry: MockConfigEntry
) -> None:
    """Rarely used counters start disabled."""
    await _setup(hass, mock_config_entry)
    registry = er.async_get(hass)
    for unique_id in (
        f"{C}_on_demand_pickups",
        f"{C}_extra_bags",
        f"{C}_1001_interventions",
    ):
        entry = registry.async_get(_entity_id(hass, unique_id))
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_new_year_resets_this_year(
    hass: HomeAssistant,
    portal: FakePortal,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """At midnight on January 1st the yearly sensors drop to zero."""
    frozen_time.move_to("2026-12-31T23:59:00+01:00")
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, f"{C}_1001_weight_this_year")
    assert float(hass.states.get(entity_id).state) > 0

    frozen_time.move_to("2027-01-01T00:00:05+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "0"
    assert (
        hass.states.get(entity_id)
        .attributes["last_reset"]
        .startswith("2027-01-01T00:00:00")
    )


async def test_portal_outage_makes_entities_unavailable(
    hass: HomeAssistant,
    portal: FakePortal,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A failed update marks entities unavailable until the next success."""
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, f"{C}_balance")
    portal.down = True
    await _refresh(hass, frozen_time)
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    portal.down = False
    await _refresh(hass, frozen_time)
    assert hass.states.get(entity_id).state == "35.09"


async def test_removed_container_removes_device(
    hass: HomeAssistant,
    portal: FakePortal,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A container that disappears from the account loses its device."""
    await _setup(hass, mock_config_entry)
    paper = get_device(hass, f"{C}_1002", mock_config_entry)
    assert paper
    assert not await async_remove_config_entry_device(hass, mock_config_entry, paper)

    page = load_fixture("containers.html")
    portal.overrides["/Aansluitpunten/Containers"] = re.sub(
        r"<h3>papier / karton</h3>.*?</table>", "", page, flags=re.S
    )
    await _refresh(hass, frozen_time)

    assert get_device(hass, f"{C}_1002", mock_config_entry) is None
    assert get_device(hass, f"{C}_1001", mock_config_entry)


async def test_chart_image(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    portal: FakePortal,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The statistics chart is served through the image proxy."""
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, f"{C}_chart_restafval", "image")
    state = hass.states.get(entity_id)
    client = await hass_client()
    response = await client.get(state.attributes["entity_picture"])
    assert response.status == HTTPStatus.OK
    assert (await response.read()).startswith(b"\x89PNG")
