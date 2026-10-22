"""Data update coordinator for the Diftar integration."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DiftarAuthError, DiftarClient, DiftarError
from .const import (
    CALENDAR_REFRESH_BEFORE_END,
    CALENDAR_UPDATE_INTERVAL,
    CONF_MUNICIPALITY,
    CONF_STREET,
    DOMAIN,
    LOGGER,
    UPDATE_INTERVAL,
)
from .iok import IokAddressError, IokCalendarClient, IokError, Pickup, split_address
from .models import DiftarData
from .statistics import async_import_history

type DiftarConfigEntry = ConfigEntry[DiftarCoordinator]


class DiftarCoordinator(DataUpdateCoordinator[DiftarData]):
    """Fetch all account data from mijndiftar.be."""

    config_entry: DiftarConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: DiftarConfigEntry, client: DiftarClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        # Registered in async_setup_entry, before the platforms are set up.
        self.account_device_id: str = ""
        self.calendar: IokCalendarCoordinator | None = None

    async def _async_update_data(self) -> DiftarData:
        try:
            data = await self.client.async_get_data()
        except DiftarAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except DiftarError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if "recorder" in self.hass.config.components:
            async_import_history(self.hass, data)
        return data


class IokCalendarCoordinator(DataUpdateCoordinator[list[Pickup]]):
    """Fetch the collection calendar for the address of the account.

    Kept apart from the portal data: when iok.be is down or does not know the
    street, only the calendar entities become unavailable.
    """

    config_entry: DiftarConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DiftarConfigEntry,
        client: IokCalendarClient,
        account: DiftarCoordinator,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_calendar",
            update_interval=CALENDAR_UPDATE_INTERVAL,
        )
        self.client = client
        self._account = account
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.calendar.{entry.entry_id}"
        )
        self._cache: dict[str, Any] | None = None

    @property
    def address(self) -> tuple[str, str] | None:
        """Return (municipality, street): from the options, else the portal."""
        options = self.config_entry.options
        if options.get(CONF_MUNICIPALITY) and options.get(CONF_STREET):
            return options[CONF_MUNICIPALITY], options[CONF_STREET]
        account = self._account.data.account
        return split_address(account.street, account.city)

    async def _async_update_data(self) -> list[Pickup]:
        if (address := self.address) is None:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="address_unknown"
            )
        if self._cache is None:
            self._cache = await self._store.async_load() or {}
        cached = self._cached_pickups(address)
        if cached is not None and not self._running_out(cached):
            return cached
        try:
            pickups = await self.client.async_get_pickups(*address)
        except IokAddressError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="address_not_found",
                translation_placeholders={
                    "street": address[1],
                    "municipality": address[0],
                },
            ) from err
        except IokError as err:
            if cached is not None:
                # Only refreshing ahead of the year end: keep what we have.
                LOGGER.debug("Keeping the stored calendar: %s", err)
                return cached
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="calendar_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._cache = {
            "address": list(address),
            "fetched_on": dt_util.now().date().isoformat(),
            "pickups": [[p.day.isoformat(), p.code] for p in pickups],
        }
        await self._store.async_save(self._cache)
        return pickups

    def _cached_pickups(self, address: tuple[str, str]) -> list[Pickup] | None:
        """Return the stored calendar if it belongs to this address."""
        if not self._cache or self._cache.get("address") != list(address):
            return None
        try:
            return [
                Pickup(day=date.fromisoformat(day), code=code)
                for day, code in self._cache["pickups"]
            ]
        except (KeyError, TypeError, ValueError):
            return None

    def _running_out(self, pickups: list[Pickup]) -> bool:
        """Return True when the calendar needs to be downloaded again.

        That is when it ends within a month (next year's calendar may be
        online by then), but at most once a day.
        """
        today = dt_util.now().date()
        if self._cache and self._cache.get("fetched_on") == today.isoformat():
            return False
        last = max((pickup.day for pickup in pickups), default=today)
        return last - today < CALENDAR_REFRESH_BEFORE_END
