"""Tests for the HTML and JSON parsers."""

from __future__ import annotations

from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

from custom_components.diftar import parser

from .conftest import load_fixture

TZ = ZoneInfo("Europe/Brussels")


def test_parse_account() -> None:
    """The connection point header is parsed."""
    account = parser.parse_account(load_fixture("containers.html"))
    assert account.customer_number == "1234567"
    assert account.reference_person == "Janssens,Jan"
    assert account.residents == 1
    assert account.payment_reference == "123456789012"
    assert account.address == "Kerkstraat 1, 2440 Geel"


def test_parse_containers() -> None:
    """Every container table is parsed."""
    containers = parser.parse_containers(load_fixture("containers.html"))
    assert [c.container_id for c in containers] == ["1001", "1002"]
    rest, paper = containers
    assert rest.fraction == "restafval"
    assert rest.fraction_name == "restafval"
    assert rest.description == "restafvalcontainer 120 L"
    assert rest.volume == 120
    assert rest.number == "000111111"
    assert rest.issued == date(2007, 6, 8)
    assert rest.returned is None
    assert rest.locked is False
    assert rest.blocked is False
    assert paper.fraction_name == "papier / karton"
    assert paper.volume == 240


def test_parse_balance_and_invitations() -> None:
    """Balance and payment invitations are parsed."""
    assert parser.parse_balance(load_fixture("verrichtingen.html")) == 35.09
    invitations = parser.parse_payment_invitations(
        load_fixture("betalingsuitnodigingen.html")
    )
    assert len(invitations) == 3
    assert invitations[0].created_on == date(2026, 4, 2)
    assert invitations[0].amount == 89.88
    assert invitations[0].paid is True
    assert invitations[0].due_on == date(2026, 5, 21)


def test_empty_pages() -> None:
    """Pages without a table count zero rows."""
    for name in ("berichten.html", "ophalingen.html", "extrazakken.html"):
        assert parser.count_table_rows(load_fixture(name)) == 0
    assert parser.count_table_rows(load_fixture("interventies.html")) == 0


def test_parse_charts() -> None:
    """The statistics chart urls are parsed and unescaped."""
    charts = parser.parse_charts(
        load_fixture("statistieken.html"), "https://www.mijndiftar.be"
    )
    assert len(charts) == 1
    assert charts[0].fraction_name == "restafval"
    assert charts[0].url.startswith(
        "https://www.mijndiftar.be/Statistiek/PersoonlijkEnGemeenteHistoriek?"
    )
    assert "&amp;" not in charts[0].url


def test_parse_collections() -> None:
    """Collections are parsed newest first with a timezone."""
    rows = json.loads(load_fixture("inzamelingen_restafval.json"))["aaData"]
    collections = parser.parse_collections(rows, TZ)
    assert len(collections) == 77
    assert collections[0].collected_at == datetime(2026, 10, 15, 8, 49, tzinfo=TZ)
    assert collections[0].weight == 27.0


def test_parse_transactions() -> None:
    """Transactions are parsed with signed amounts."""
    rows = json.loads(load_fixture("verrichtingen.json"))["aaData"]
    transactions = parser.parse_transactions(rows)
    assert len(transactions) == 133
    first = transactions[0]
    assert first.booked_on == date(2026, 10, 16)
    assert first.kind == "gewicht"
    assert first.amount == -8.1
    assert "000111111" in first.description
    assert any(t.kind == "betaling" and t.amount > 0 for t in transactions)


def test_parse_number() -> None:
    """Belgian number formats are handled."""
    assert parser.parse_number("€ -1.234,50") == -1234.5
    assert parser.parse_number("<div class='cRight'>27,0</div>") == 27.0
    assert parser.parse_number("") is None
    assert parser.parse_number("n/a") is None


def test_login_pages() -> None:
    """Login form and its error message are detected."""
    assert parser.is_login_page(load_fixture("logon.html"))
    assert not parser.is_login_page(load_fixture("containers.html"))
    assert parser.login_error(load_fixture("logon.html")) is None
    assert "niet gevonden" in (
        parser.login_error(load_fixture("logon_failed.html")) or ""
    )


def test_count_table_rows_with_rows() -> None:
    """Header rows are skipped, body rows are counted."""
    page = (
        '<div id="content"><table id="x"><thead><tr><th>a</th></tr></thead>'
        "<tbody><tr><td>1</td></tr><tr><td>2</td></tr></tbody></table></div>"
    )
    assert parser.count_table_rows(page) == 2
