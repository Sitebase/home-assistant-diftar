"""Base entities for the Diftar integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, BASE_URL, DOMAIN
from .coordinator import DiftarCoordinator
from .models import Container

# Home Assistant 2026.8 links child devices by device id; older versions only
# accept the (domain, identifier) tuple of the parent.
VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


def account_device_info(customer_number: str) -> DeviceInfo:
    """Return the device info of the connection point."""
    return DeviceInfo(
        identifiers={(DOMAIN, customer_number)},
        name="Diftar",
        manufacturer="IOK Afvalbeheer",
        model="Diftar connection point",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=f"{BASE_URL}/Aansluitpunten",
    )


class DiftarEntity(CoordinatorEntity[DiftarCoordinator]):
    """An entity that belongs to the connection point device."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DiftarCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        account = coordinator.data.account
        self._customer_number = account.customer_number
        self._attr_unique_id = f"{account.customer_number}_{description.key}"
        self._attr_device_info = account_device_info(account.customer_number)


class DiftarContainerEntity(CoordinatorEntity[DiftarCoordinator]):
    """An entity that belongs to one container."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DiftarCoordinator,
        description: EntityDescription,
        container_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.container_id = container_id
        customer_number = coordinator.data.account.customer_number
        container = coordinator.data.containers[container_id]
        self._attr_unique_id = f"{customer_number}_{container_id}_{description.key}"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{customer_number}_{container_id}")},
            name=f"Diftar {container.fraction_name}",
            manufacturer="IOK Afvalbeheer",
            model=container.description,
            serial_number=container.number,
            configuration_url=f"{BASE_URL}/Aansluitpunten/Inzamelingen/{container_id}",
        )
        if VIA_DEVICE_ID:
            device_info["via_device_id"] = coordinator.account_device_id
        else:
            device_info["via_device"] = (DOMAIN, customer_number)  # type: ignore[typeddict-unknown-key]
        self._attr_device_info = device_info

    @property
    def container(self) -> Container | None:
        """Return the container, or None when it is no longer on the account."""
        return self.coordinator.data.containers.get(self.container_id)

    @property
    def available(self) -> bool:
        """Return True when the container is still linked to the account."""
        return super().available and self.container is not None
