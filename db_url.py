"""db_url.py - Resolve and normalize the PostgreSQL connection URL."""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PLACEHOLDER_DATABASE_URLS = {
    "postgresql://user:password@localhost/travelport_db",
    "postgresql://user:password@localhost/GDS_Automation",
}


def _is_placeholder_database_url(database_url: str | None) -> bool:
    normalized = (database_url or "").strip()
    if not normalized:
        return True
    if normalized in PLACEHOLDER_DATABASE_URLS:
        return True
    return "YOUR_" in normalized.upper()


def _normalize_database_url(database_url: str | None) -> str:
    """Normalize PostgreSQL URLs so psycopg2 can consume them reliably."""
    normalized = (database_url or "").strip()
    if not normalized:
        return ""

    if normalized.startswith("postgresql+"):
        normalized = "postgresql://" + normalized.split("://", 1)[1]

    if normalized.startswith("postgresql://"):
        parts = urlsplit(normalized)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.setdefault("connect_timeout", "5")
        normalized = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query),
                parts.fragment,
            )
        )

    return normalized


def _resolve_database_url(config: dict) -> str:
    """Prefer DATABASE_URL, but fall back to config when it isn't a placeholder."""
    env_database_url = _normalize_database_url(os.environ.get("DATABASE_URL"))
    if env_database_url:
        return env_database_url

    config_database_url = config.get("database_url")
    if _is_placeholder_database_url(config_database_url):
        return ""

    return _normalize_database_url(config_database_url)
