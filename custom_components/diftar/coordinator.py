"""Data update coordinator for the Diftar integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DiftarAuthError, DiftarClient, DiftarError
from .const import DOMAIN, LOGGER, UPDATE_INTERVAL
from .models import DiftarData

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

    async def _async_update_data(self) -> DiftarData:
        try:
            return await self.client.async_get_data()
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
