"""Persistent, domain-keyed store for sourced companies.

This module intentionally has no API-key or network dependency.  Later pipeline
stages should use :class:`DedupStore` to avoid processing a domain already seen
in a previous run.
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_DATABASE_PATH = Path("data") / "leads.sqlite3"


@dataclass(frozen=True)
class StoredCompany:
    """A company retained for domain-based deduplication."""

    domain: str
    company_name: str
    first_seen_at: str


@dataclass(frozen=True)
class StoredSignal:
    """Source evidence associated with a stored company."""

    signal_type: str
    date_found: str
    raw_evidence_text: str


@dataclass(frozen=True)
class SignalSummary:
    """Signals associated with a domain, ready for later pipeline stages."""

    domain: str
    total_signals: int
    signals: tuple[StoredSignal, ...]


@dataclass(frozen=True)
class FilteredCompany:
    """An auditable persisted result of applying the ICP hard filters."""

    domain: str
    company_name: str
    passed: bool
    reasons: tuple[str, ...]
    filtered_at: str


def normalize_domain(domain_or_url: str) -> str:
    """Return a canonical domain suitable as a deduplication key.

    Accepts a bare domain or an HTTP(S) URL.  Paths, query strings, ports, a
    trailing dot, and a leading ``www.`` are removed.  The function rejects
    malformed values rather than silently storing an unusable key.
    """

    value = domain_or_url.strip()
    if not value:
        raise ValueError("A company domain is required.")

    parsed = urlparse(value if "://" in value else f"//{value}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Could not extract a domain from {domain_or_url!r}.")

    normalized = hostname.rstrip(".").lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if not normalized or "." not in normalized:
        raise ValueError(f"{domain_or_url!r} is not a valid company domain.")

    return normalized.encode("idna").decode("ascii")


class DedupStore:
    """A SQLite-backed, persistent store keyed by normalized company domain."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        """Create the database and schema if they do not already exist."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    domain TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS filtered_companies (
                    domain TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
                    reasons_json TEXT NOT NULL,
                    filtered_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS company_signals (
                    id INTEGER PRIMARY KEY,
                    domain TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    date_found TEXT NOT NULL,
                    raw_evidence_text TEXT NOT NULL,
                    FOREIGN KEY (domain) REFERENCES companies(domain),
                    UNIQUE (domain, signal_type, date_found, raw_evidence_text)
                )
                """
            )

    def exists(self, domain_or_url: str) -> bool:
        """Return whether this normalized company domain was stored before."""

        domain = normalize_domain(domain_or_url)
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM companies WHERE domain = ?", (domain,)
            ).fetchone()
        return row is not None

    def add(
        self,
        company_name: str,
        domain_or_url: str,
        signal_type: str,
        date_found: str,
        raw_evidence_text: str,
    ) -> bool:
        """Store a company and its source evidence, returning whether it is new.

        A company is stored only once per normalized domain, but every distinct
        signal is retained in ``company_signals``. Repeating the exact same
        signal is ignored. ``True`` means a new company was created; ``False``
        means its domain was already present (even if a new signal was saved).
        """

        cleaned_name = company_name.strip()
        if not cleaned_name:
            raise ValueError("A company name is required.")
        cleaned_signal_type = signal_type.strip()
        if not cleaned_signal_type:
            raise ValueError("A signal type is required.")
        cleaned_date_found = date_found.strip()
        if not cleaned_date_found:
            raise ValueError("A date found is required.")
        cleaned_evidence = raw_evidence_text.strip()
        if not cleaned_evidence:
            raise ValueError("Raw evidence text is required.")

        domain = normalize_domain(domain_or_url)
        first_seen_at = datetime.now(timezone.utc).isoformat()
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO companies (domain, company_name, first_seen_at)
                VALUES (?, ?, ?)
                """,
                (domain, cleaned_name, first_seen_at),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO company_signals
                    (domain, signal_type, date_found, raw_evidence_text)
                VALUES (?, ?, ?, ?)
                """,
                (domain, cleaned_signal_type, cleaned_date_found, cleaned_evidence),
            )
        return cursor.rowcount == 1

    def get(self, domain_or_url: str) -> StoredCompany | None:
        """Return the stored company for a domain, or ``None`` if it is new."""

        domain = normalize_domain(domain_or_url)
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT domain, company_name, first_seen_at
                FROM companies
                WHERE domain = ?
                """,
                (domain,),
            ).fetchone()
        return StoredCompany(*row) if row else None

    def list_domains(self) -> set[str]:
        """Return all domains already persisted before a pipeline run starts."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT domain FROM companies").fetchall()
        return {row[0] for row in rows}

    def get_signals(self, domain_or_url: str) -> list[StoredSignal]:
        """Return every distinct source signal stored for a company."""

        domain = normalize_domain(domain_or_url)
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT signal_type, date_found, raw_evidence_text
                FROM company_signals
                WHERE domain = ?
                ORDER BY id
                """,
                (domain,),
            ).fetchall()
        return [StoredSignal(*row) for row in rows]

    def get_signal_summary(self, domain_or_url: str) -> SignalSummary:
        """Return all signal evidence and its total for a normalized domain."""

        domain = normalize_domain(domain_or_url)
        signals = self.get_signals(domain)
        return SignalSummary(domain=domain, total_signals=len(signals), signals=tuple(signals))

    def save_filter_result(
        self,
        company_name: str,
        domain_or_url: str,
        passed: bool,
        reasons: list[str] | tuple[str, ...],
    ) -> None:
        """Upsert an ICP filter decision so every evaluated company is auditable."""

        cleaned_name = company_name.strip()
        if not cleaned_name:
            raise ValueError("A company name is required.")
        domain = normalize_domain(domain_or_url)
        filtered_at = datetime.now(timezone.utc).isoformat()
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO companies (domain, company_name, first_seen_at)
                VALUES (?, ?, ?)
                """,
                (domain, cleaned_name, filtered_at),
            )
            connection.execute(
                """
                INSERT INTO filtered_companies
                    (domain, company_name, passed, reasons_json, filtered_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    company_name = excluded.company_name,
                    passed = excluded.passed,
                    reasons_json = excluded.reasons_json,
                    filtered_at = excluded.filtered_at
                """,
                (domain, cleaned_name, int(passed), json.dumps(list(reasons)), filtered_at),
            )

    def get_filter_result(self, domain_or_url: str) -> FilteredCompany | None:
        """Return the most recent persisted filter result for a company."""

        domain = normalize_domain(domain_or_url)
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT domain, company_name, passed, reasons_json, filtered_at
                FROM filtered_companies
                WHERE domain = ?
                """,
                (domain,),
            ).fetchone()
        if not row:
            return None
        return FilteredCompany(
            domain=row[0],
            company_name=row[1],
            passed=bool(row[2]),
            reasons=tuple(json.loads(row[3])),
            filtered_at=row[4],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA journal_mode = WAL")
        return connection
