"""Image entities with the yearly weight charts from mijndiftar.be."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util, slugify

from .coordinator import DiftarConfigEntry, DiftarCoordinator
from .entity import DiftarEntity
from .models import StatisticsChart

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DiftarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the statistics chart images."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_charts() -> None:
        new = [
            chart.fraction_name
            for chart in coordinator.data.charts
            if chart.fraction_name not in known
        ]
        if not new:
            return
        known.update(new)
        async_add_entities(DiftarChartImage(coordinator, name) for name in new)

    _add_charts()
    entry.async_on_unload(coordinator.async_add_listener(_add_charts))


class DiftarChartImage(DiftarEntity, ImageEntity):
    """Yearly weight of the household vs. the municipality median."""

    _attr_content_type = "image/png"

    def __init__(self, coordinator: DiftarCoordinator, fraction_name: str) -> None:
        """Initialize the image."""
        super().__init__(
            coordinator,
            ImageEntityDescription(
                key=f"chart_{slugify(fraction_name)}",
                translation_key="chart",
            ),
        )
        ImageEntity.__init__(self, coordinator.hass)
        self._fraction_name = fraction_name
        self._attr_translation_placeholders = {"fraction": fraction_name}
        self._image: bytes | None = None
        self._update_image()

    def _chart(self) -> StatisticsChart | None:
        return next(
            (
                chart
                for chart in self.coordinator.data.charts
                if chart.fraction_name == self._fraction_name
            ),
            None,
        )

    def _update_image(self) -> None:
        chart = self._chart()
        image = chart.image if chart else None
        if image != self._image:
            self._image = image
            self._attr_image_last_updated = dt_util.utcnow()
        if chart:
            self._attr_content_type = chart.content_type

    @property
    def available(self) -> bool:
        """Return True when the chart could be downloaded."""
        return super().available and self._image is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_image()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the chart bytes."""
        return self._image
