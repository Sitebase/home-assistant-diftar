"""The Diftar integration: waste data from mijndiftar.be in Home Assistant."""

from __future__ import annotations

from datetime import datetime

from aiohttp import CookieJar

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import DiftarClient
from .const import DOMAIN
from .coordinator import DiftarConfigEntry, DiftarCoordinator
from .entity import account_device_info

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.IMAGE, Platform.SENSOR]


def _device_identifiers(coordinator: DiftarCoordinator) -> set[tuple[str, str]]:
    """Return the identifiers of every device the current data describes."""
    customer_number = coordinator.data.account.customer_number
    return {(DOMAIN, customer_number)} | {
        (DOMAIN, f"{customer_number}_{container_id}")
        for container_id in coordinator.data.containers
    }


async def async_setup_entry(hass: HomeAssistant, entry: DiftarConfigEntry) -> bool:
    """Set up Diftar from a config entry."""
    # The portal is session based: give every entry its own cookie jar and
    # close the session when the entry unloads.
    session = async_create_clientsession(
        hass, auto_cleanup=False, cookie_jar=CookieJar()
    )
    entry.async_on_unload(session.close)
    client = DiftarClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = DiftarCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # The container devices link to this one, so it must exist first.
    coordinator.account_device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id,
            **account_device_info(coordinator.data.account.customer_number),
        )
        .id
    )

    @callback
    def _remove_stale_devices() -> None:
        """Drop devices of containers that are no longer on the account."""
        if not coordinator.last_update_success:
            return
        current = _device_identifiers(coordinator)
        device_registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        ):
            if not device.identifiers & current:
                # Devices belong to a single config entry since HA 2026.10,
                # which deprecates remove_config_entry_id for this.
                device_registry.async_remove_device(device.id)

    @callback
    def _new_year(now: datetime) -> None:
        """Reset the "this year" sensors right at midnight on January 1st.

        The yearly values are derived from the cached data, so notifying the
        listeners is enough; the other listeners are no-ops on unchanged data.
        """
        if now.month == 1 and now.day == 1 and coordinator.last_update_success:
            coordinator.async_update_listeners()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _remove_stale_devices()
    entry.async_on_unload(coordinator.async_add_listener(_remove_stale_devices))
    entry.async_on_unload(
        async_track_time_change(hass, _new_year, hour=0, minute=0, second=5)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DiftarConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DiftarConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device that is no longer on the account."""
    return not device_entry.identifiers & _device_identifiers(entry.runtime_data)
