"""Sensors for the Diftar integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import DiftarConfigEntry
from .entity import DiftarContainerEntity, DiftarEntity
from .models import Container, DiftarData, Transaction

PARALLEL_UPDATES = 0

CURRENCY_EURO = "EUR"
TOP_UP_KIND = "betaling"
RECENT_COLLECTIONS = 10


def _this_year() -> int:
    return dt_util.now().year


def _start_of_year() -> datetime:
    return dt_util.start_of_local_day(date(_this_year(), 1, 1))


def _container_transactions(
    data: DiftarData, container: Container
) -> list[Transaction]:
    """Return the bookings that mention the container number."""
    return [
        transaction
        for transaction in data.transactions
        if container.number and container.number in transaction.description
    ]


def _costs(transactions: list[Transaction], year: int) -> float:
    """Return the money spent in a year (charges are negative amounts)."""
    return round(
        -sum(
            transaction.amount
            for transaction in transactions
            if transaction.booked_on.year == year and transaction.amount < 0
        ),
        2,
    )


def _weight(container: Container, year: int) -> float:
    return round(
        sum(
            collection.weight
            for collection in container.collections
            if collection.collected_at.year == year
        ),
        2,
    )


def _collection_count(container: Container, year: int) -> int:
    return sum(
        1
        for collection in container.collections
        if collection.collected_at.year == year
    )


def _last_top_up(data: DiftarData) -> Transaction | None:
    return next(
        (
            transaction
            for transaction in data.transactions
            if transaction.kind == TOP_UP_KIND and transaction.amount > 0
        ),
        None,
    )


def _open_invitations_amount(data: DiftarData) -> float:
    return round(
        sum(
            invitation.amount or 0
            for invitation in data.payment_invitations
            if not invitation.paid
        ),
        2,
    )


@dataclass(frozen=True, kw_only=True)
class DiftarSensorEntityDescription(SensorEntityDescription):
    """Describes an account sensor."""

    value_fn: Callable[[DiftarData], Any]
    attributes_fn: Callable[[DiftarData], dict[str, Any] | None] = lambda _: None
    last_reset_fn: Callable[[], datetime | None] = lambda: None


@dataclass(frozen=True, kw_only=True)
class DiftarContainerSensorEntityDescription(SensorEntityDescription):
    """Describes a container sensor."""

    value_fn: Callable[[Container, DiftarData], Any]
    attributes_fn: Callable[[Container, DiftarData], dict[str, Any] | None] = (
        lambda _container, _data: None
    )
    last_reset_fn: Callable[[], datetime | None] = lambda: None


ACCOUNT_SENSORS: tuple[DiftarSensorEntityDescription, ...] = (
    DiftarSensorEntityDescription(
        key="balance",
        translation_key="balance",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: data.balance,
    ),
    DiftarSensorEntityDescription(
        key="costs_this_year",
        translation_key="costs_this_year",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _costs(data.transactions, _this_year()),
        last_reset_fn=_start_of_year,
    ),
    DiftarSensorEntityDescription(
        key="costs_last_year",
        translation_key="costs_last_year",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _costs(data.transactions, _this_year() - 1),
    ),
    DiftarSensorEntityDescription(
        key="last_transaction",
        translation_key="last_transaction",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: (
            data.transactions[0].booked_on if data.transactions else None
        ),
        attributes_fn=lambda data: (
            {
                "type": data.transactions[0].kind,
                "description": data.transactions[0].description,
                "amount": data.transactions[0].amount,
            }
            if data.transactions
            else None
        ),
    ),
    DiftarSensorEntityDescription(
        key="last_top_up",
        translation_key="last_top_up",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: (
            top_up.booked_on if (top_up := _last_top_up(data)) else None
        ),
        attributes_fn=lambda data: (
            {"amount": top_up.amount, "description": top_up.description}
            if (top_up := _last_top_up(data))
            else None
        ),
    ),
    DiftarSensorEntityDescription(
        key="open_payment_amount",
        translation_key="open_payment_amount",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=_open_invitations_amount,
        attributes_fn=lambda data: {
            "invitations": [
                {
                    "reference": invitation.reference,
                    "created_on": invitation.created_on,
                    "due_on": invitation.due_on,
                    "amount": invitation.amount,
                    "paid": invitation.paid,
                }
                for invitation in data.payment_invitations
            ]
        },
    ),
    DiftarSensorEntityDescription(
        key="messages",
        translation_key="messages",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.messages,
    ),
    DiftarSensorEntityDescription(
        key="on_demand_pickups",
        translation_key="on_demand_pickups",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.on_demand_pickups,
    ),
    DiftarSensorEntityDescription(
        key="extra_bags",
        translation_key="extra_bags",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.extra_bags,
    ),
    DiftarSensorEntityDescription(
        key="residents",
        translation_key="residents",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.account.residents,
        attributes_fn=lambda data: {"address": data.account.address},
    ),
)


def _recent_collections(container: Container, _data: DiftarData) -> dict[str, Any]:
    return {
        "collections": [
            {
                "collected_at": collection.collected_at.isoformat(),
                "weight": collection.weight,
            }
            for collection in container.collections[:RECENT_COLLECTIONS]
        ]
    }


CONTAINER_SENSORS: tuple[DiftarContainerSensorEntityDescription, ...] = (
    DiftarContainerSensorEntityDescription(
        key="last_collection",
        translation_key="last_collection",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda container, _: (
            container.collections[0].collected_at if container.collections else None
        ),
        attributes_fn=_recent_collections,
    ),
    DiftarContainerSensorEntityDescription(
        key="last_collection_weight",
        translation_key="last_collection_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        value_fn=lambda container, _: (
            container.collections[0].weight if container.collections else None
        ),
    ),
    DiftarContainerSensorEntityDescription(
        key="weight_this_year",
        translation_key="weight_this_year",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        value_fn=lambda container, _: _weight(container, _this_year()),
        last_reset_fn=_start_of_year,
    ),
    DiftarContainerSensorEntityDescription(
        key="weight_last_year",
        translation_key="weight_last_year",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        value_fn=lambda container, _: _weight(container, _this_year() - 1),
    ),
    DiftarContainerSensorEntityDescription(
        key="collections_this_year",
        translation_key="collections_this_year",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda container, _: _collection_count(container, _this_year()),
        last_reset_fn=_start_of_year,
    ),
    DiftarContainerSensorEntityDescription(
        key="costs_this_year",
        translation_key="container_costs_this_year",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda container, data: _costs(
            _container_transactions(data, container), _this_year()
        ),
        last_reset_fn=_start_of_year,
    ),
    DiftarContainerSensorEntityDescription(
        key="issued",
        translation_key="issued",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda container, _: container.issued,
        attributes_fn=lambda container, _: {
            "number": container.number,
            "volume": container.volume,
            "returned": container.returned,
        },
    ),
    DiftarContainerSensorEntityDescription(
        key="interventions",
        translation_key="interventions",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda container, _: container.interventions,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DiftarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Diftar sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        DiftarSensor(coordinator, description) for description in ACCOUNT_SENSORS
    )

    known: set[str] = set()

    @callback
    def _add_containers() -> None:
        new = set(coordinator.data.containers) - known
        if not new:
            return
        known.update(new)
        async_add_entities(
            DiftarContainerSensor(coordinator, description, container_id)
            for container_id in new
            for description in CONTAINER_SENSORS
        )

    _add_containers()
    entry.async_on_unload(coordinator.async_add_listener(_add_containers))


class DiftarSensor(DiftarEntity, SensorEntity):
    """An account level sensor."""

    entity_description: DiftarSensorEntityDescription

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attributes_fn(self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        """Return the start of the period for yearly totals."""
        return self.entity_description.last_reset_fn()


class DiftarContainerSensor(DiftarContainerEntity, SensorEntity):
    """A container level sensor."""

    entity_description: DiftarContainerSensorEntityDescription

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if (container := self.container) is None:
            return None
        return self.entity_description.value_fn(container, self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if (container := self.container) is None:
            return None
        return self.entity_description.attributes_fn(container, self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        """Return the start of the period for yearly totals."""
        return self.entity_description.last_reset_fn()
