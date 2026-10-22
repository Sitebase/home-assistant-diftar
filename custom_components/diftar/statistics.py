"""Import the full portal history into long-term statistics.

The sensors only summarise this year and last year. The portal keeps every
collection since the container was issued, so the history is written as
external statistics; statistics graphs can then show any period, e.g. one bar
per year. The full history is rewritten on every update: rows are keyed by
hour, so this is idempotent and also picks up corrections made by IOK.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import MassConverter

from .const import DOMAIN
from .models import DiftarData

CURRENCY_EURO = "EUR"


def weight_statistic_id(container_id: str) -> str:
    """Return the statistic id with the weight history of a container."""
    return f"{DOMAIN}:container_{container_id}_weight"


def collections_statistic_id(container_id: str) -> str:
    """Return the statistic id with the number of collections of a container."""
    return f"{DOMAIN}:container_{container_id}_collections"


def costs_statistic_id(customer_number: str) -> str:
    """Return the statistic id with the costs of the account."""
    return f"{DOMAIN}:account_{customer_number}_costs"


def _hourly(points: Iterable[tuple[datetime, float]]) -> list[StatisticData]:
    """Bucket (time, value) points per hour and add the running sum."""
    buckets: dict[datetime, float] = defaultdict(float)
    for moment, value in points:
        buckets[moment.replace(minute=0, second=0, microsecond=0)] += value
    total = 0.0
    rows: list[StatisticData] = []
    for start in sorted(buckets):
        total += buckets[start]
        rows.append(
            StatisticData(
                start=start, state=round(buckets[start], 2), sum=round(total, 2)
            )
        )
    return rows


def _metadata(
    statistic_id: str, name: str, unit: str | None, unit_class: str | None
) -> StatisticMetaData:
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )


@callback
def async_import_history(hass: HomeAssistant, data: DiftarData) -> None:
    """Write the collection and cost history as external statistics."""
    for container in data.containers.values():
        if not container.collections:
            continue
        name = f"Diftar {container.fraction_name}"
        async_add_external_statistics(
            hass,
            _metadata(
                weight_statistic_id(container.container_id),
                f"{name} weight",
                UnitOfMass.KILOGRAMS,
                MassConverter.UNIT_CLASS,
            ),
            _hourly((c.collected_at, c.weight) for c in container.collections),
        )
        async_add_external_statistics(
            hass,
            _metadata(
                collections_statistic_id(container.container_id),
                f"{name} collections",
                None,
                None,
            ),
            _hourly((c.collected_at, 1) for c in container.collections),
        )

    charges = [
        (dt_util.start_of_local_day(t.booked_on), -t.amount)
        for t in data.transactions
        if t.amount < 0
    ]
    if charges:
        async_add_external_statistics(
            hass,
            _metadata(
                costs_statistic_id(data.account.customer_number),
                "Diftar costs",
                CURRENCY_EURO,
                None,
            ),
            _hourly(charges),
        )
