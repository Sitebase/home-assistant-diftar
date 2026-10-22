# Diftar for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/Sitebase/home-assistant-diftar/actions/workflows/validate.yaml/badge.svg)](https://github.com/Sitebase/home-assistant-diftar/actions/workflows/validate.yaml)
[![Tests](https://github.com/Sitebase/home-assistant-diftar/actions/workflows/tests.yaml/badge.svg)](https://github.com/Sitebase/home-assistant-diftar/actions/workflows/tests.yaml)

Brings your [mijndiftar.be](https://www.mijndiftar.be) account (IOK Afvalbeheer, Kempen) into Home Assistant:

- **Balance and costs**: prepaid balance, costs per year and per container, payment invitations.
- **Every collection**: date, time and weight of each emptying, per container.
- **Full history**: all collections and costs since the start, as long-term statistics.
- **Collection calendar**: upcoming pickups from iok.be, as a calendar and "next pickup" sensors.
- **Statistics chart**: your household vs. the municipality median.

> Unofficial. Not affiliated with IOK Afvalbeheer. The portal has no public API, so this integration reads the same pages you see when you log in.

## Contents

- [Installation](#installation)
- [Setup](#setup)
- [Entities](#entities)
- [Collection calendar](#collection-calendar)
- [Full history](#full-history)
- [Example dashboard](#example-dashboard)
- [Updates and limitations](#updates-and-limitations)
- [Troubleshooting](#troubleshooting)
- [Privacy](#privacy)
- [Removal](#removal)
- [Development](#development)

## Installation

Requires Home Assistant **2026.6** or newer.

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Sitebase&repository=home-assistant-diftar&category=integration)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/Sitebase/home-assistant-diftar`, type **Integration**.
2. Search for **Diftar**, install it and restart Home Assistant.

### Manual

Copy `custom_components/diftar` into the `custom_components` folder of your Home Assistant config and restart.

## Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=diftar)

1. **Settings → Devices & services → Add integration → Diftar**.
2. Enter the username and password you use on mijndiftar.be.

Login via eID / itsme is not supported: set a password in the portal first (*gebruikersnaam of wachtwoord vergeten?*).

| Change | Where |
|---|---|
| Password changed | Home Assistant asks for the new one (re-authentication) |
| Username | Integration → ⋮ → **Reconfigure** |
| Address for the collection calendar | Integration → **Configure** (options) |

## Entities

All entities belong to a **Diftar** device, with one extra device per container (e.g. *Diftar restafval*).

### Account

| Entity | Source (portal page) | Notes |
|---|---|---|
| Balance | Saldo en verrichtingen | € |
| Costs this year / last year | Saldo en verrichtingen | sum of all charges (weight, emptying, monthly base fee) |
| Last transaction / Last top-up | Saldo en verrichtingen | date; type, description and amount as attributes |
| Open payment amount | Betalingsuitnodigingen | all invitations as attribute |
| Payment due (binary) | Betalingsuitnodigingen | on when an invitation is unpaid |
| Residents | Detail aansluitpunt | address as attribute |
| Messages | Berichten | count |
| On-demand pickups, Extra bags | Ophalingen op afroep, Extra zakken | count, disabled by default |
| Statistics (image) | Statistieken | yearly chart: you vs. the municipality median |

### Per container

| Entity | Source (portal page) | Notes |
|---|---|---|
| Last collection | Inzamelingen | timestamp; last 10 collections as attribute |
| Last collection weight | Inzamelingen | kg |
| Weight this year / last year | Inzamelingen | kg |
| Collections this year | Inzamelingen | count |
| Costs this year | Saldo en verrichtingen | € for this container |
| Issued | Containers en inzamelingen | date; number, volume, return date as attributes |
| Lock, Blocked (binary) | Containers en inzamelingen | |
| Interventions | Interventies | count, disabled by default |

### Collection calendar

| Entity | Notes |
|---|---|
| Collection calendar | all pickups, one all-day event per fraction |
| Next pickup | date; fractions and upcoming pickups as attributes |
| Next *fraction* pickup | one per fraction (restafval, GFT, PMD, papier / karton, …); `days_until` as attribute |

Disabled-by-default entities are 0 for almost everyone; enable them under the device if you use those services.

## Collection calendar

The portal links to the calendar on iok.be. The integration takes the street and municipality of your connection point (house number and postcode are not needed), selects it on iok.be and downloads the calendar file (*Toevoegen aan agenda*).

- The file is stored and **downloaded once**.
- It is downloaded again only when the address changes or the calendar runs out (from December, once a day until next year's calendar is online). If that fails, the stored calendar is kept.
- If iok.be lists your street under another (sub)municipality, set the address in the integration options.

| Code | Fraction |
|---|---|
| RA | Restafval |
| GFT | GFT |
| PMD | PMD |
| P/K | Papier / karton |
| GV | Grofvuil |
| TEXT | Textiel |

## Full history

The sensors summarise this year and last year. On every update the integration also imports the **complete history from the portal into long-term statistics**: collections go back to when the container was issued, bookings a few years.

| Statistic id | Content |
|---|---|
| `diftar:container_<id>_weight` | kg per collection |
| `diftar:container_<id>_collections` | number of collections |
| `diftar:account_<customer number>_costs` | € charged (weight, emptying, base fee) |

Use them in a *Statistics graph* card with `period: year` (or month, week) and `stat_types: [change]` for one bar per period. Find your ids under **Developer tools → Statistics** (search "diftar"). Requires the recorder, which is enabled by default.

## Example dashboard

[`examples/dashboard.yaml`](examples/dashboard.yaml) is a complete sections dashboard:

- next pickups and the collection calendar,
- balance and costs,
- a section per container with a recent collections table,
- the statistics chart,
- monthly and yearly history graphs.

Replace the container ids and customer number in the statistic ids with yours.

## Updates and limitations

| Data | Refresh |
|---|---|
| Portal (balance, collections, history) | every 4 hours; collections are booked a day after pickup |
| Collection calendar | stored; downloaded again only when needed (see above) |
| Date based values (next pickup, "this year") | roll over at midnight |

Not supported yet:

- Underground containers with badges (no test account). Open an issue with an anonymised page if you have them.
- Accounts with more than one connection point: only the first one is read.
- The counts of on-demand pickups, extra bags and interventions are based on the tables those pages show when they have entries; not yet verified with a non-empty account.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Entities unavailable | The portal is down or rejected the request; retried on the next poll. A log warning *portal layout may have changed* means pages no longer parse: please open an issue. |
| Calendar entities unavailable | iok.be is down or does not know the street. Check the log and set the address in the options. |
| Re-authentication requested | The password changed or the account is blocked. Check on mijndiftar.be, then enter the new password. |
| A container disappeared | Returned bins are removed from the account; the device is removed on the next update. |

**Debug logging**: use *Enable debug logging* on the integration page, or add `custom_components.diftar: debug` under `logger: logs:`. **Diagnostics** can be downloaded from the integration page; personal data is redacted.

## Privacy

- Credentials are stored in the Home Assistant config entry and only sent to `www.mijndiftar.be`.
- The street and municipality (no house number) are sent to `www.iok.be` to fetch the collection calendar.
- Diagnostics redact the username, password, customer number, address, name and container numbers.

## Removal

1. Settings → Devices & services → Diftar → ⋮ → **Delete**.
2. Remove the repository in HACS (or delete `custom_components/diftar`) and restart.

## Development

```bash
uv venv -p 3.14
uv pip install pytest-homeassistant-custom-component==0.13.373 ruff==0.17.2
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against anonymised copies of the real portal and iok.be pages in `tests/fixtures`. CI also runs them against the oldest supported Home Assistant release.
