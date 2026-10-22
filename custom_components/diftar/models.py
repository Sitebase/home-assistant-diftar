"""Data models for the Diftar integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(slots=True)
class Account:
    """A connection point (aansluitpunt) on mijndiftar.be."""

    customer_number: str
    street: str | None = None
    city: str | None = None
    reference_person: str | None = None
    residents: int | None = None
    payment_reference: str | None = None

    @property
    def address(self) -> str | None:
        """Return the full address of the connection point."""
        parts = [part for part in (self.street, self.city) if part]
        return ", ".join(parts) or None


@dataclass(slots=True)
class Collection:
    """A single emptying of a container."""

    collected_at: datetime
    weight: float


@dataclass(slots=True)
class Container:
    """A wheelie bin linked to the connection point."""

    container_id: str
    fraction: str
    fraction_name: str
    description: str
    number: str
    volume: int | None = None
    issued: date | None = None
    returned: date | None = None
    locked: bool | None = None
    blocked: bool | None = None
    collections: list[Collection] = field(default_factory=list)
    interventions: int = 0


@dataclass(slots=True)
class Transaction:
    """A booking on the prepaid Diftar balance."""

    booked_on: date
    kind: str
    description: str
    amount: float


@dataclass(slots=True)
class PaymentInvitation:
    """A payment invitation (betalingsuitnodiging) to top up the balance."""

    created_on: date | None
    reference: str
    amount: float | None
    paid: bool
    due_on: date | None


@dataclass(slots=True)
class StatisticsChart:
    """A yearly weight chart (own household vs. municipality median)."""

    fraction_name: str
    url: str
    image: bytes | None = None
    content_type: str = "image/png"


@dataclass(slots=True)
class DiftarData:
    """Everything fetched from the account in one update."""

    account: Account
    containers: dict[str, Container] = field(default_factory=dict)
    balance: float | None = None
    transactions: list[Transaction] = field(default_factory=list)
    payment_invitations: list[PaymentInvitation] = field(default_factory=list)
    messages: int = 0
    on_demand_pickups: int = 0
    extra_bags: int = 0
    charts: list[StatisticsChart] = field(default_factory=list)
