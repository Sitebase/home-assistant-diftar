"""Binary sensors for the Diftar integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DiftarConfigEntry
from .entity import DiftarContainerEntity, DiftarEntity
from .models import Container, DiftarData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DiftarBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an account binary sensor."""

    value_fn: Callable[[DiftarData], bool | None]
    attributes_fn: Callable[[DiftarData], dict[str, Any] | None] = lambda _: None


@dataclass(frozen=True, kw_only=True)
class DiftarContainerBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a container binary sensor."""

    value_fn: Callable[[Container], bool | None]


def _unpaid_invitation(data: DiftarData) -> dict[str, Any] | None:
    unpaid = [
        invitation for invitation in data.payment_invitations if not invitation.paid
    ]
    if not unpaid:
        return None
    first = min(unpaid, key=lambda invitation: invitation.due_on or date.max)
    return {
        "reference": first.reference,
        "amount": first.amount,
        "due_on": first.due_on,
    }


ACCOUNT_BINARY_SENSORS: tuple[DiftarBinarySensorEntityDescription, ...] = (
    DiftarBinarySensorEntityDescription(
        key="payment_due",
        translation_key="payment_due",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: any(
            not invitation.paid for invitation in data.payment_invitations
        ),
        attributes_fn=_unpaid_invitation,
    ),
)

CONTAINER_BINARY_SENSORS: tuple[DiftarContainerBinarySensorEntityDescription, ...] = (
    DiftarContainerBinarySensorEntityDescription(
        key="locked",
        translation_key="locked",
        device_class=BinarySensorDeviceClass.LOCK,
        # The lock device class reports "on" for unlocked.
        value_fn=lambda container: (
            None if container.locked is None else not container.locked
        ),
    ),
    DiftarContainerBinarySensorEntityDescription(
        key="blocked",
        translation_key="blocked",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda container: container.blocked,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DiftarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Diftar binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        DiftarBinarySensor(coordinator, description)
        for description in ACCOUNT_BINARY_SENSORS
    )

    known: set[str] = set()

    @callback
    def _add_containers() -> None:
        new = set(coordinator.data.containers) - known
        if not new:
            return
        known.update(new)
        async_add_entities(
            DiftarContainerBinarySensor(coordinator, description, container_id)
            for container_id in new
            for description in CONTAINER_BINARY_SENSORS
        )

    _add_containers()
    entry.async_on_unload(coordinator.async_add_listener(_add_containers))


class DiftarBinarySensor(DiftarEntity, BinarySensorEntity):
    """An account level binary sensor."""

    entity_description: DiftarBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attributes_fn(self.coordinator.data)


class DiftarContainerBinarySensor(DiftarContainerEntity, BinarySensorEntity):
    """A container level binary sensor."""

    entity_description: DiftarContainerBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        if (container := self.container) is None:
            return None
        return self.entity_description.value_fn(container)
