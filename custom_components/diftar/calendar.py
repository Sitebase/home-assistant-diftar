"""Collection calendar (ophaalkalender) from iok.be."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import IOK_ATTRIBUTION
from .coordinator import DiftarConfigEntry, IokCalendarCoordinator
from .entity import account_device_info
from .iok import Pickup

PARALLEL_UPDATES = 0


def _event(pickup: Pickup) -> CalendarEvent:
    return CalendarEvent(
        start=pickup.day,
        end=pickup.day + timedelta(days=1),
        summary=pickup.name,
        uid=f"{pickup.day.isoformat()}_{pickup.code}",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DiftarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the collection calendar."""
    coordinator = entry.runtime_data
    if coordinator.calendar is not None:
        async_add_entities(
            [
                DiftarCalendar(
                    coordinator.calendar, coordinator.data.account.customer_number
                )
            ]
        )


class DiftarCalendar(CoordinatorEntity[IokCalendarCoordinator], CalendarEntity):
    """All pickups for the address of the connection point."""

    _attr_attribution = IOK_ATTRIBUTION
    _attr_has_entity_name = True
    _attr_translation_key = "collection_calendar"

    def __init__(
        self, coordinator: IokCalendarCoordinator, customer_number: str
    ) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{customer_number}_collection_calendar"
        self._attr_device_info = account_device_info(customer_number)

    def _pickups(self, start: date, end: date) -> list[Pickup]:
        return [
            pickup
            for pickup in self.coordinator.data or []
            if start <= pickup.day < end
        ]

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next pickup (today's pickup counts until midnight)."""
        today = dt_util.now().date()
        upcoming = self._pickups(today, date.max)
        return _event(upcoming[0]) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the pickups in a date range."""
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date() + timedelta(days=1)
        return [_event(pickup) for pickup in self._pickups(start, end)]
