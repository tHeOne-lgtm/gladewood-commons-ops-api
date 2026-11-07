"""Database engine, session dependency, and connection-string normalization."""
import re
from collections.abc import Iterator
from urllib.parse import quote, unquote

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings


def _extract_dsn(raw: str) -> str:
    """Pull the postgres URL out of whatever was pasted. Supabase's dashboard
    shows a '# Connect via ...' hint that is easy to copy with the URL, and a
    single-line env field can turn the newline into a literal backslash-n."""
    raw = (raw or "").strip()
    idx = raw.find("postgresql://")
    if idx == -1:
        idx = raw.find("postgres://")
    if idx == -1:
        return raw.strip('"').strip("'")
    tail = raw[idx:].strip().strip('"').strip("'")
    return re.split(r"\s|\\n", tail)[0]


def _normalize_dsn(raw_url: str) -> str:
    """Re-encode the userinfo so special characters in the password cannot
    break URL parsing, and drop the pgbouncer hint libpq does not accept."""
    raw_url = raw_url.strip()
    m = re.match(r"^(postgres(?:ql)?://)(.+)$", raw_url)
    if not m:
        return raw_url
    scheme, remainder = m.groups()
    if "@" not in remainder:
        return raw_url
    userinfo, rest = remainder.rsplit("@", 1)
    if ":" in userinfo:
        user, pwd = userinfo.split(":", 1)
    else:
        user, pwd = userinfo, ""
    user_enc = quote(unquote(user), safe="")
    pwd_enc = quote(unquote(pwd), safe="")
    rest = rest.strip()
    if "?" in rest:
        host_part, query = rest.split("?", 1)
        kept = [p for p in query.split("&") if p and not p.startswith("pgbouncer")]
        rest = host_part + ("?" + "&".join(kept) if kept else "")
    return f"{scheme}{user_enc}:{pwd_enc}@{rest}"


def normalize_database_url(raw: str) -> str:
    """Return a SQLAlchemy URL using the psycopg 3 driver."""
    dsn = _normalize_dsn(_extract_dsn(raw))
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+psycopg://" + dsn[len("postgresql://"):]
    return dsn


def mask_database_url(dsn: str) -> str:
    """Redact the password even when the DSN is malformed."""
    m = re.match(r"^([a-z+]+://[^:/]+:)(.*)$", dsn)
    if not m:
        return f"<unparseable DSN, length={len(dsn)}>"
    prefix, remainder = m.groups()
    at_idx = remainder.rfind("@")
    if at_idx == -1:
        return prefix + f"***<no @ found, length={len(remainder)}>"
    return prefix + "***" + remainder[at_idx:]


def make_engine(url: str, settings: Settings | None = None) -> Engine:
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    settings = settings or Settings()
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session
