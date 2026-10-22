"""Parse the mijndiftar.be HTML pages and DataTables JSON responses.

The portal is a server-rendered ASP.NET MVC site without a public API. The
markup is generated, so a few targeted regular expressions are enough and
keep the integration free of extra dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, tzinfo
import html as html_lib
import re
from typing import Any

from .models import (
    Account,
    Collection,
    Container,
    PaymentInvitation,
    StatisticsChart,
    Transaction,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TABLE_RE = re.compile(
    r"<h3>(?P<title>[^<]*)</h3>\s*<table[^>]*\bid=\"(?P<id>[^\"]+)\"[^>]*>(?P<body>.*?)</table>",
    re.S | re.I,
)
_ANY_TABLE_RE = re.compile(r"<table[^>]*>(?P<body>.*?)</table>", re.S | re.I)
_TBODY_RE = re.compile(r"<tbody>(.*?)</tbody>", re.S | re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_INZAMELINGEN_RE = re.compile(r"/Aansluitpunten/Inzamelingen/(\d+)", re.I)
_LABEL_FIELD_RE = re.compile(
    r"<div class=\"detailASP-label\">(?P<label>.*?)</div>\s*"
    r"<div class=\"detailASP-field\">(?P<value>.*?)</div>\s*<div class=\"clearer\">",
    re.S | re.I,
)
_OGM_RE = re.compile(r"id=\"AansluitpuntDetail_Ogm\"[^>]*value=\"(\d+)\"", re.I)
_ADDRESS_RE = re.compile(
    r"<div class=\"right\">\s*<div class=\"display-field\">(?P<street>.*?)</div>\s*"
    r"<div class=\"display-field\">(?P<city>.*?)</div>",
    re.S | re.I,
)
_BALANCE_RE = re.compile(r"huidig saldo.*?(-?\s*€?\s*-?[\d.]+,\d{2})", re.S | re.I)
_VOLUME_RE = re.compile(r"(\d+)\s*L\b", re.I)
_CHART_RE = re.compile(
    r"<h3>(?P<title>[^<]*)</h3>\s*<img[^>]*src=\"(?P<src>/Statistiek/[^\"]+)\"",
    re.S | re.I,
)
_LOGIN_FORM_RE = re.compile(r"name=\"AuthenticationValue\"", re.I)
_VALIDATION_RE = re.compile(
    r"<div class=\"validation-summary-errors\"[^>]*>(.*?)</div>", re.S | re.I
)


def clean(value: str) -> str:
    """Strip tags, decode entities and collapse whitespace."""
    return _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", value))).strip()


def parse_number(value: str) -> float | None:
    """Parse a Belgian formatted number such as '€ -1.234,50' or '27,0'."""
    text = clean(value).replace("€", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: str) -> date | None:
    """Parse a dd/mm/yyyy date."""
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_bool(value: str) -> bool | None:
    """Parse a Dutch ja/nee value."""
    text = clean(value).lower()
    if text == "ja":
        return True
    if text == "nee":
        return False
    return None


def _content(page: str) -> str:
    """Return the main content block of a portal page."""
    index = page.find('<div id="content">')
    return page[index:] if index >= 0 else page


def _rows(table_html: str) -> list[list[str]]:
    """Return the raw cells of every body row in a table."""
    body = _TBODY_RE.search(table_html)
    source = body.group(1) if body else table_html
    rows = []
    for row in _ROW_RE.findall(source):
        cells = _CELL_RE.findall(row)
        if cells and "<th" not in row.lower():
            rows.append(cells)
    return rows


def is_login_page(page: str) -> bool:
    """Return True when the page is the login form (session expired)."""
    return bool(_LOGIN_FORM_RE.search(page))


def login_error(page: str) -> str | None:
    """Return the validation message shown after a failed login, if any."""
    if match := _VALIDATION_RE.search(page):
        return clean(match.group(1)) or None
    return None


def parse_account(page: str) -> Account:
    """Parse the connection point header shown on every Aansluitpunten page."""
    fields = {
        clean(match.group("label")).lower(): clean(match.group("value"))
        for match in _LABEL_FIELD_RE.finditer(page)
    }
    customer_number = fields.get("klantnummer")
    if not customer_number:
        raise ValueError("Customer number not found on page")

    residents: int | None = None
    if (raw := fields.get("aantal bewoners")) and raw.isdigit():
        residents = int(raw)

    account = Account(
        customer_number=customer_number,
        reference_person=fields.get("referentiepersoon") or None,
        residents=residents,
    )
    if match := _OGM_RE.search(page):
        account.payment_reference = match.group(1)
    if match := _ADDRESS_RE.search(page):
        account.street = clean(match.group("street")) or None
        account.city = clean(match.group("city")) or None
    return account


def parse_containers(page: str) -> list[Container]:
    """Parse the container tables, one table per waste fraction."""
    containers: list[Container] = []
    for table in _TABLE_RE.finditer(_content(page)):
        for cells in _rows(table.group("body")):
            if len(cells) < 7:
                continue
            link = _INZAMELINGEN_RE.search(cells[6])
            if not link:
                continue
            description = clean(cells[0])
            volume = _VOLUME_RE.search(description)
            containers.append(
                Container(
                    container_id=link.group(1),
                    fraction=table.group("id"),
                    fraction_name=clean(table.group("title")),
                    description=description,
                    number=clean(cells[1]),
                    volume=int(volume.group(1)) if volume else None,
                    issued=parse_date(cells[2]),
                    returned=parse_date(cells[3]),
                    locked=parse_bool(cells[4]),
                    blocked=parse_bool(cells[5]),
                )
            )
    return containers


def parse_balance(page: str) -> float | None:
    """Parse the current prepaid balance."""
    if match := _BALANCE_RE.search(_content(page)):
        return parse_number(match.group(1))
    return None


def parse_payment_invitations(page: str) -> list[PaymentInvitation]:
    """Parse the payment invitations table."""
    match = re.search(
        r"<table[^>]*\bid=\"BetalingsUitnodigingen\"[^>]*>(.*?)</table>", page, re.S
    )
    if not match:
        return []
    invitations = []
    for cells in _rows(match.group(1)):
        if len(cells) < 5:
            continue
        invitations.append(
            PaymentInvitation(
                created_on=parse_date(cells[0]),
                reference=clean(cells[1]),
                amount=parse_number(cells[2]),
                paid=parse_bool(cells[3]) is True,
                due_on=parse_date(cells[4]),
            )
        )
    return invitations


def count_table_rows(page: str) -> int:
    """Count body rows of the tables in the content block.

    Used for pages that only show a table when there is something to list
    (messages, on-demand pickups, extra bags, interventions).
    """
    return sum(
        len(_rows(table.group("body")))
        for table in _ANY_TABLE_RE.finditer(_content(page))
    )


def parse_charts(page: str, base_url: str) -> list[StatisticsChart]:
    """Parse the statistics chart image urls, one per fraction."""
    return [
        StatisticsChart(
            fraction_name=clean(match.group("title")),
            url=base_url + html_lib.unescape(match.group("src")),
        )
        for match in _CHART_RE.finditer(_content(page))
    ]


def parse_collections(rows: Iterable[list[Any]], tz: tzinfo) -> list[Collection]:
    """Parse DataTables rows of ['dd/mm/yyyy - HH:MM', '<div>27,0</div>']."""
    collections = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            collected_at = datetime.strptime(
                clean(str(row[0])), "%d/%m/%Y - %H:%M"
            ).replace(tzinfo=tz)
        except ValueError:
            continue
        collections.append(
            Collection(
                collected_at=collected_at, weight=parse_number(str(row[1])) or 0.0
            )
        )
    collections.sort(key=lambda item: item.collected_at, reverse=True)
    return collections


def parse_transactions(rows: Iterable[list[Any]]) -> list[Transaction]:
    """Parse DataTables rows of [date, type, description, amount]."""
    transactions = []
    for row in rows:
        if len(row) < 4:
            continue
        booked_on = parse_date(str(row[0]))
        amount = parse_number(str(row[3]))
        if booked_on is None or amount is None:
            continue
        transactions.append(
            Transaction(
                booked_on=booked_on,
                kind=clean(str(row[1])),
                description=clean(str(row[2])),
                amount=amount,
            )
        )
    transactions.sort(key=lambda item: item.booked_on, reverse=True)
    return transactions
