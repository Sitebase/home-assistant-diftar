# Diftar for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/Sitebase/home-assistant-diftar/actions/workflows/validate.yaml/badge.svg)](https://github.com/Sitebase/home-assistant-diftar/actions/workflows/validate.yaml)

Brings your [mijndiftar.be](https://www.mijndiftar.be) account (IOK Afvalbeheer, Kempen) into Home Assistant: prepaid balance, costs, every collection of every container and its weight, payment invitations and the yearly statistics chart.

> Unofficial. Not affiliated with IOK Afvalbeheer. The portal has no public API, so this integration reads the same pages you see when you log in.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/Sitebase/home-assistant-diftar`, type **Integration**.
2. Search for **Diftar**, install it and restart Home Assistant.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Sitebase&repository=home-assistant-diftar&category=integration)

Requires Home Assistant 2026.6 or newer. The icon ships with the integration (shown in Home Assistant); the HACS store list shows a default icon until the integration is added to [home-assistant/brands](https://github.com/home-assistant/brands).

### Manual

Copy `custom_components/diftar` into the `custom_components` folder of your Home Assistant config and restart.

## Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=diftar)

**Settings → Devices & services → Add integration → Diftar**, then enter the username and password you use on mijndiftar.be. Login via eID / itsme is not supported: set a password in the portal first (*gebruikersnaam of wachtwoord vergeten?*).

If the password changes, Home Assistant asks for the new one (re-authentication). Use **Reconfigure** on the integration to change the username.

## What the account offers, and what becomes an entity

| Portal page | Data | Home Assistant |
|---|---|---|
| Detail aansluitpunt | address, reference person, customer number, residents, payment reference (OGM) | `Diftar` device, *Residents* sensor (address as attribute) |
| Containers en inzamelingen | per container: type, volume, number, issue/return date, lock, blocked | one device per container, *Issued* sensor, *Lock* and *Blocked* binary sensors |
| Inzamelingen (per container) | every emptying with date, time and weight | *Last collection*, *Last collection weight*, *Weight this year / last year*, *Collections this year*; the last 10 collections as attribute |
| Saldo en verrichtingen | current balance, every booking (weight, emptying, monthly base fee, payments) | *Balance*, *Costs this year / last year*, *Last transaction*, *Last top-up*, per container *Costs this year* |
| Betalingsuitnodigingen | payment invitations with amount, paid, due date | *Open payment amount* (all invitations as attribute), *Payment due* binary sensor |
| Statistieken | yearly chart: your household vs. the municipality median for the same household size | *Statistics* image entity |
| Interventies (per container) | repairs/replacements | *Interventions* sensor |
| Berichten, Ophalingen op afroep, Extra zakken | messages, on-demand pickups, extra bags | count sensors |

| Ophaalkalender (iok.be) | pickup dates for every fraction for the rest of the year | *Collection calendar* entity, *Next pickup* and *Next &lt;fraction&gt; pickup* date sensors (with `days_until`) |

### Collection calendar

The portal links to the calendar on iok.be. The integration takes the street and municipality of your connection point, selects it on iok.be and downloads the calendar file (*Toevoegen aan agenda*). The file is stored and **downloaded once**: again only when the address changes or the calendar runs out (from December, once a day until next year's calendar is online). If iok.be knows your street under another (sub)municipality, set it in the integration **options**.

Codes: RA = restafval, GFT, PMD, P/K = papier/karton, GV = grofvuil, TEXT = textiel.

Not included:
- Underground containers with badges are not parsed yet (no test account). Open an issue with an anonymised page if you have them.
- Accounts with more than one connection point: only the first one is read.

### Full history

The sensors summarise this year and last year. On every update the integration also imports the **complete history from the portal into long-term statistics** (collections go back to when the container was issued, bookings a few years):

| Statistic id | Content |
|---|---|
| `diftar:container_<id>_weight` | kg per collection |
| `diftar:container_<id>_collections` | number of collections |
| `diftar:account_<customer number>_costs` | € charged (weight, emptying, base fee) |

Use them in a *Statistics graph* card with `period: year` (or month/week) and `stat_types: [change]` for one bar per period; see the example dashboard. Find the ids under Developer tools → Statistics. Requires the recorder (enabled by default).

Data refreshes every 4 hours. Collections are booked a day after pickup.

*On-demand pickups*, *Extra bags* and *Interventions* are disabled by default (they are 0 for almost everyone); enable them under the device if you use those services. Their counts are based on the tables those pages show when they have entries, which could not be verified with a real non-empty account yet.

## Troubleshooting

- **Entities unavailable**: the portal is down or rejected the request. The integration retries on the next poll. A warning *portal layout may have changed* in the log means pages no longer parse; please open an issue.
- **Re-authentication requested**: the password changed or the account is blocked. Log in on mijndiftar.be to check, then enter the new password in Home Assistant.
- **A container disappeared**: when a bin is returned it is removed from the account, and its device is removed automatically on the next update.
- **Debug logging**: add `custom_components.diftar: debug` under `logger: logs:` or use *Enable debug logging* on the integration page. Download diagnostics from the integration page; personal data is redacted.

## Removal

Settings → Devices & services → Diftar → ⋮ → **Delete**. Then remove the repository in HACS (or delete `custom_components/diftar`) and restart.

## Example dashboard

[`examples/dashboard.yaml`](examples/dashboard.yaml) is a complete sections dashboard (balance, per-container weights, recent collections table, statistics chart, monthly and yearly history graphs).

## Privacy

Credentials are stored in the Home Assistant config entry and only sent to `www.mijndiftar.be`. Diagnostics redact the username, password, customer number, address, name and container numbers.

## Development

```bash
uv venv -p 3.14 && uv pip install pytest-homeassistant-custom-component ruff
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests run against anonymised copies of the real portal pages in `tests/fixtures`.
