import os
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import get_db
from app.main import create_app
from app.models import Base, User

TEST_SECRET = "test-secret-at-least-thirty-two-bytes-long!!"
ADMIN_EMAIL = "admin@example.com"
ALLOWED_ORIGIN = "http://localhost:3000"


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        eng = create_engine(url, pool_pre_ping=True)
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    manage_schema = not os.environ.get("TEST_SKIP_CREATE_ALL")
    if manage_schema:
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
    yield eng
    if manage_schema:
        Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        env="test",
        database_url="sqlite://",
        supabase_jwt_secret=TEST_SECRET,
        cors_origins=ALLOWED_ORIGIN,
        bootstrap_admin_emails=ADMIN_EMAIL,
    )


@pytest.fixture
def app(db, settings):
    application = create_app(settings)
    application.dependency_overrides[get_db] = lambda: db
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def make_token(sub: str, email: str, *, secret: str = TEST_SECRET, aud: str = "authenticated",
               exp_offset: int = 3600) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "email": email, "aud": aud, "iat": now, "exp": now + exp_offset, "role": "authenticated"},
        secret,
        algorithm="HS256",
    )


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    return auth(make_token(str(uuid.uuid4()), ADMIN_EMAIL))


@pytest.fixture
def staff_user(db):
    user = User(id=str(uuid.uuid4()), email="staff@example.com", role="staff")
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def staff_headers(staff_user):
    return auth(make_token(staff_user.id, staff_user.email))


@pytest.fixture
def pending_headers():
    return auth(make_token(str(uuid.uuid4()), "nobody@example.com"))


@pytest.fixture
def pipelines(db):
    from app.seed import seed_default_pipelines
    seed_default_pipelines(db)
    db.commit()
    from app.models import Pipeline
    from sqlalchemy import select
    return {p.slug: p for p in db.scalars(select(Pipeline)).all()}
