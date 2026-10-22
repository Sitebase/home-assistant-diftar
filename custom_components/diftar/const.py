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
IOK_ATTRIBUTION: Final = "Data provided by iok.be"

# iok.be publishes the calendar once a year. The downloaded ICS is cached and
# only fetched again when the address changes or the calendar runs out (in
# December, until next year's calendar is online). The daily check is local.
CALENDAR_UPDATE_INTERVAL: Final = timedelta(days=1)
CALENDAR_REFRESH_BEFORE_END: Final = timedelta(days=31)

# Options: override the address used for the iok.be collection calendar.
CONF_MUNICIPALITY: Final = "municipality"
CONF_STREET: Final = "street"
