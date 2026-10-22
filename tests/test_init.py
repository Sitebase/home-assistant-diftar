"""Tests for setting up the Diftar integration and its entities."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.diftar.const import DOMAIN, UPDATE_INTERVAL
from custom_components.diftar.diagnostics import async_get_config_entry_diagnostics
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import CUSTOMER_NUMBER, FakePortal


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time after the last fixture collection."""
    freezer.move_to("2026-10-22T12:00:00+02:00")
    return freezer


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, unique_id: str, domain: str = "sensor") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, unique_id
    state = hass.states.get(entity_id)
    assert state, entity_id
    return state.state


async def test_setup_and_entities(
    hass: HomeAssistant, portal: FakePortal, mock_config_entry: MockConfigEntry
) -> None:
    """All account and container entities are created with values."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    c = CUSTOMER_NUMBER
    assert _state(hass, f"{c}_balance") == "35.09"
    assert _state(hass, f"{c}_residents") == "1"
    assert _state(hass, f"{c}_messages") == "0"
    assert _state(hass, f"{c}_open_payment_amount") == "0"
    assert _state(hass, f"{c}_last_transaction") == "2026-10-16"
    assert float(_state(hass, f"{c}_costs_this_year")) > 0
    assert _state(hass, f"{c}_payment_due", "binary_sensor") == "off"

    assert _state(hass, f"{c}_1001_last_collection") == "2026-10-15T06:49:00+00:00"
    assert _state(hass, f"{c}_1001_last_collection_weight") == "27.0"
    assert float(_state(hass, f"{c}_1001_weight_this_year")) > 0
    assert int(_state(hass, f"{c}_1001_collections_this_year")) > 0
    assert float(_state(hass, f"{c}_1001_costs_this_year")) > 0
    assert _state(hass, f"{c}_1001_issued") == "2007-06-08"
    assert _state(hass, f"{c}_1001_blocked", "binary_sensor") == "off"
    # The lock device class reports "off" for locked: the bin has no lock.
    assert _state(hass, f"{c}_1001_locked", "binary_sensor") == "on"
    assert _state(hass, f"{c}_1002_last_collection_weight") == "0.0"
    assert _state(hass, f"{c}_chart_restafval", "image") != "unavailable"

    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), mock_config_entry.entry_id
    )
    assert sorted(device.name for device in devices) == [
        "Diftar",
        "Diftar papier / karton",
        "Diftar restafval",
    ]

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_session_expiry_logs_in_again(
    hass: HomeAssistant,
    portal: FakePortal,
    mock_config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """An expired session triggers one new login, not a reauth."""
    await _setup(hass, mock_config_entry)
    logins = portal.logins
    portal.logged_in = False

    frozen_time.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert portal.logins == logins + 1
    assert _state(hass, f"{CUSTOMER_NUMBER}_balance") == "35.09"


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, portal: FakePortal, mock_config_entry: MockConfigEntry
) -> None:
    """A rejected password puts the entry in reauth."""
    portal.password = "changed"
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_portal_down_retries(
    hass: HomeAssistant, portal: FakePortal, mock_config_entry: MockConfigEntry
) -> None:
    """A portal outage makes setup retry."""
    portal.down = True
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_are_redacted(
    hass: HomeAssistant, portal: FakePortal, mock_config_entry: MockConfigEntry
) -> None:
    """Diagnostics never contain credentials or personal data."""
    await _setup(hass, mock_config_entry)
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    text = str(result)
    for secret in ("secret", "Janssens", "Kerkstraat", "123456789012", CUSTOMER_NUMBER):
        assert secret not in text
    assert result["data"]["containers"]["1001"]["volume"] == 120
