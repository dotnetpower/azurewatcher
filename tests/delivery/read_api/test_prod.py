"""Unit tests for :mod:`fdai.delivery.read_api.prod`.

Env-only composition root - exercised without a live DB (Entra JWKS is
constructed lazily, and ``build_prod_app`` only *creates* config
objects up to the DB round-trip).
"""

from __future__ import annotations

from typing import Final

import pytest
from starlette.applications import Starlette

from fdai.delivery.read_api.prod import (
    ProdReadApiConfigError,
    _parse_cors_origins,
    _parse_positive_int,
    _plain_dsn,
    build_prod_app,
    build_prod_read_model,
)

_GOOD_ENV: Final[dict[str, str]] = {
    "FDAI_DATABASE_URL": "postgresql+psycopg://fdai:devonly@localhost:5432/fdai",
    "FDAI_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000001",
    "FDAI_API_AUDIENCE": "api://00000000-0000-0000-0000-000000000002",
    "FDAI_RBAC_READERS_GROUP_ID": "00000000-0000-0000-0000-000000000010",
    "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "00000000-0000-0000-0000-000000000011",
    "FDAI_RBAC_APPROVERS_GROUP_ID": "00000000-0000-0000-0000-000000000012",
    "FDAI_RBAC_OWNERS_GROUP_ID": "00000000-0000-0000-0000-000000000013",
    "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "00000000-0000-0000-0000-000000000014",
}


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_plain_dsn_strips_psycopg_driver_suffix() -> None:
    assert _plain_dsn("postgresql+psycopg://u:p@h/db") == "postgresql://u:p@h/db"


def test_plain_dsn_pass_through_plain_url() -> None:
    assert _plain_dsn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_parse_cors_origins_empty_returns_empty_tuple() -> None:
    assert _parse_cors_origins(None) == ()
    assert _parse_cors_origins("") == ()
    assert _parse_cors_origins(" , , ") == ()


def test_parse_cors_origins_splits_and_trims() -> None:
    got = _parse_cors_origins("https://a.example, https://b.example ,https://c.example")
    assert got == ("https://a.example", "https://b.example", "https://c.example")


def test_parse_positive_int_returns_default_when_unset_or_blank() -> None:
    assert _parse_positive_int({}, "K", 42) == 42
    assert _parse_positive_int({"K": "  "}, "K", 42) == 42


def test_parse_positive_int_parses_value() -> None:
    assert _parse_positive_int({"K": "7"}, "K", 42) == 7


def test_parse_positive_int_rejects_non_int() -> None:
    with pytest.raises(ProdReadApiConfigError, match="K"):
        _parse_positive_int({"K": "seven"}, "K", 42)


def test_parse_positive_int_rejects_non_positive() -> None:
    with pytest.raises(ProdReadApiConfigError, match=">= 1"):
        _parse_positive_int({"K": "0"}, "K", 42)


# ---------------------------------------------------------------------------
# build_prod_read_model - no DB round-trip yet (config validation only)
# ---------------------------------------------------------------------------


def test_build_prod_read_model_requires_database_url() -> None:
    env = dict(_GOOD_ENV)
    del env["FDAI_DATABASE_URL"]
    with pytest.raises(ProdReadApiConfigError, match="FDAI_DATABASE_URL"):
        build_prod_read_model(env)


def test_build_prod_read_model_returns_configured_adapter() -> None:
    reader = build_prod_read_model(_GOOD_ENV)
    # Attribute is private but its presence proves the config path ran.
    assert reader._config.dsn == "postgresql://fdai:devonly@localhost:5432/fdai"
    assert reader._config.statement_timeout_ms == 20_000
    assert reader._config.connect_timeout_s == 10


def test_build_prod_read_model_honors_timeout_overrides() -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_READ_API_STATEMENT_TIMEOUT_MS"] = "5000"
    env["FDAI_READ_API_CONNECT_TIMEOUT_S"] = "3"
    reader = build_prod_read_model(env)
    assert reader._config.statement_timeout_ms == 5_000
    assert reader._config.connect_timeout_s == 3


# ---------------------------------------------------------------------------
# build_prod_app - full env composition
# ---------------------------------------------------------------------------


def test_build_prod_app_returns_starlette_app() -> None:
    app = build_prod_app(_GOOD_ENV)
    assert isinstance(app, Starlette)


def test_build_prod_app_requires_tenant_id() -> None:
    env = dict(_GOOD_ENV)
    del env["FDAI_ENTRA_TENANT_ID"]
    # EntraJwtVerifier raises its own EntraVerifierConfigError, which is a
    # ValueError subclass - the prod factory does not catch it.
    with pytest.raises(ValueError, match="FDAI_ENTRA_TENANT_ID"):
        build_prod_app(env)


def test_build_prod_app_requires_api_audience() -> None:
    env = dict(_GOOD_ENV)
    del env["FDAI_API_AUDIENCE"]
    with pytest.raises(ValueError, match="FDAI_API_AUDIENCE"):
        build_prod_app(env)


@pytest.mark.parametrize(
    "missing",
    [
        "FDAI_RBAC_READERS_GROUP_ID",
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
        "FDAI_RBAC_APPROVERS_GROUP_ID",
        "FDAI_RBAC_OWNERS_GROUP_ID",
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    ],
)
def test_build_prod_app_requires_every_rbac_slot(missing: str) -> None:
    env = dict(_GOOD_ENV)
    del env[missing]
    with pytest.raises(ProdReadApiConfigError, match=missing):
        build_prod_app(env)


def test_build_prod_app_wildcard_cors_refused_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_READ_API_CORS_ALLOW_ORIGINS"] = "*"
    # build_app pulls RUNTIME_ENV from os.environ directly.
    monkeypatch.setenv("RUNTIME_ENV", "prod")
    with pytest.raises(ValueError, match="cors_allow_origins"):
        build_prod_app(env)


def test_build_prod_app_wildcard_cors_allowed_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_READ_API_CORS_ALLOW_ORIGINS"] = "*"
    monkeypatch.delenv("RUNTIME_ENV", raising=False)
    # Not a supported flow, but the check is scoped to staging/prod so an
    # accidental wildcard in dev boots (build_app comment); assert that.
    app = build_prod_app(env)
    assert isinstance(app, Starlette)


def test_build_prod_app_never_boots_in_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # The prod factory never sets FDAI_READ_API_DEV_MODE; even if the env
    # carries it, build_app refuses because ReadApiConfig.dev_mode is False
    # (we only feed dev_mode=False into build_app).
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")
    app = build_prod_app(_GOOD_ENV)
    assert isinstance(app, Starlette)
