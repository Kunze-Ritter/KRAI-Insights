"""Smoke tests for configuration and derived connection strings."""

from insights.core.config import Settings


def _settings(**overrides) -> Settings:
    # Explicit values (init kwargs) override ambient env vars / .env, keeping
    # these tests deterministic regardless of the developer's shell environment.
    base = dict(
        insights_db_user="insights",
        insights_db_password="p@ss word/!",
        insights_db_host="db",
        insights_db_port=5432,
        insights_db_name="krai_insights",
        radix_username="",
        radix_password_base64="",
        radix_client_code="",
        radix_license_id="",
        warranty_default_days=365,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_insights_url_escapes_password() -> None:
    url = _settings().insights_sqlalchemy_url
    assert url.startswith("postgresql+psycopg://insights:")
    assert "@db:5432/krai_insights" in url
    # special chars must be percent-encoded
    assert "p@ss word/!" not in url
    assert "%40" in url and "%2F" in url


def test_fleetmgmt_url_is_pyodbc_odbc_connect() -> None:
    url = _settings(
        fleetmgmt_mssql_host="h", fleetmgmt_mssql_user="u", fleetmgmt_mssql_password="pw"
    ).fleetmgmt_sqlalchemy_url
    assert url.startswith("mssql+pyodbc:///?odbc_connect=")
    assert "ODBC+Driver+18" in url


def test_radix_configured_flag() -> None:
    assert _settings().is_radix_configured is False
    cfg = _settings(
        radix_username="u",
        radix_password_base64="cHc=",
        radix_client_code="c",
        radix_license_id="l",
    )
    assert cfg.is_radix_configured is True


def test_warranty_default_is_365() -> None:
    assert _settings().warranty_default_days == 365
