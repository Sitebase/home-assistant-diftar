"""Constants for the Diftar integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "diftar"
LOGGER = logging.getLogger(__package__)

BASE_URL: Final = "https://www.mijndiftar.be"
TIMEZONE: Final = "Europe/Brussels"

# Collections are weighed and booked once per pickup (every few weeks), so
# polling a few times a day is plenty and keeps load on the portal low.
UPDATE_INTERVAL: Final = timedelta(hours=4)

ATTRIBUTION: Final = "Data provided by mijndiftar.be (IOK Afvalbeheer)"
