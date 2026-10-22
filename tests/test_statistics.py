"""Tests for importing the portal history into long-term statistics."""

from __future__ import annotations

from datetime import datetime

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.diftar.statistics import (
    collections_statistic_id,
    costs_statistic_id,
    weight_statistic_id,
)
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import CUSTOMER_NUMBER, FakePortal


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time after the last fixture collection."""
    freezer.move_to("2026-10-22T12:00:00+02:00")
    return freezer


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Start the recorder before hass is created by the other fixtures."""


async def _yearly(hass: HomeAssistant, statistic_id: str) -> dict[int, float]:
    rows = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2020, 1, 1, tzinfo=dt_util.get_default_time_zone()),
        None,
        {statistic_id},
        "year",
        None,
        {"change"},
    )
    return {
        dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).year: round(
            row["change"], 2
        )
        for row in rows[statistic_id]
    }


async def test_full_history_is_imported(
    hass: HomeAssistant,
    portal: FakePortal,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Every collection since the first one ends up in the statistics."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    # Same totals as the chart on the portal's statistics page.
    weight = await _yearly(hass, weight_statistic_id("1001"))
    assert weight[2023] == 120.5
    assert weight[2024] == 166.5
    assert weight[2025] == 114.5
    assert weight[2026] == 155.0
    assert min(weight) == 2021

    collections = await _yearly(hass, collections_statistic_id("1002"))
    assert sum(collections.values()) == 9

    costs = await _yearly(hass, costs_statistic_id(CUSTOMER_NUMBER))
    assert costs[2026] == 90.9
    assert costs[2025] == 75.26

    # Importing again on the next update does not double the history.
    await mock_config_entry.runtime_data.async_refresh()
    await async_wait_recording_done(hass)
    assert await _yearly(hass, weight_statistic_id("1001")) == weight
