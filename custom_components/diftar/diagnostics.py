"""Diagnostics support for the Diftar integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import DiftarConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "customer_number",
    "street",
    "city",
    "reference_person",
    "payment_reference",
    "number",
    "reference",
    "description",
    "url",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DiftarConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = asdict(entry.runtime_data.data)
    for chart in data["charts"]:
        chart["image"] = len(chart["image"]) if chart["image"] else None
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(data, TO_REDACT),
    }
