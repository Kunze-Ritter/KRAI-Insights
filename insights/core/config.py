"""
Central configuration for krai-insights.

All settings load from environment variables (and `.env` in dev) via
pydantic-settings. This is the single source of truth for connection strings
to the three source systems plus the Insights DB, Radix, and Ollama.

Usage:
    from insights.core.config import get_settings
    settings = get_settings()
    engine = create_engine(settings.insights_sqlalchemy_url)
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from the environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---------------------------------------------------------------
    app_env: str = "dev"
    log_level: str = "INFO"
    # Optionales Dashboard-Passwort (gemeinsames Gate vor Mitarbeiter-Rollout).
    # Leer = offen (Dev/Docker-Netz). Gesetzt = Streamlit verlangt das Passwort.
    # Ziel langfristig: Microsoft-SSO (Entra ID) statt geteiltem Passwort.
    dashboard_password: str = ""

    # --- Insights DB (own PostgreSQL — the only DB we write to) ------------
    insights_db_host: str = "localhost"
    insights_db_port: int = 5433
    insights_db_name: str = "krai_insights"
    insights_db_user: str = "insights"
    insights_db_password: str = ""

    # --- FleetMgmt (MSSQL, read-only) --------------------------------------
    fleetmgmt_mssql_host: str = "host.docker.internal"
    fleetmgmt_mssql_port: int = 1433
    fleetmgmt_mssql_db: str = "FleetMgmt"
    fleetmgmt_mssql_user: str = ""
    fleetmgmt_mssql_password: str = ""
    fleetmgmt_mssql_driver: str = "ODBC Driver 18 for SQL Server"
    fleetmgmt_mssql_trust_cert: bool = True

    # --- KRAI PostgreSQL (krai_pm schema, read-only) -----------------------
    krai_pg_host: str = "host.docker.internal"
    krai_pg_port: int = 5432
    krai_pg_db: str = "krai"
    krai_pg_user: str = ""
    krai_pg_password: str = ""
    krai_pg_schema: str = "krai_pm"

    # --- Radix RxPlusService API -------------------------------------------
    radix_api_url: str = "https://radix.kunze-ritter.de/IM.RxPlusService.Api"
    radix_api_language: str = "DE"
    radix_username: str = ""
    radix_password_base64: str = ""
    radix_client_code: str = ""
    radix_license_id: str = ""
    radix_token_cache_path: str = ".cache/radix_token.json"
    radix_token_refresh_margin_seconds: int = 60

    # --- LLM provider for the agent ----------------------------------------
    # "ollama" (local) or "openrouter" (hosted, OpenAI-compatible). The agent works
    # with either; OpenRouter gives access to stronger free models (better tool-calling
    # + German analysis). Falls back to Ollama if openrouter is selected without a key.
    llm_provider: str = "ollama"

    # --- Ollama -------------------------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    # --- OpenRouter (optional hosted backend) ------------------------------
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    # --- Business rules -----------------------------------------------------
    warranty_default_days: int = 365
    customer_mapping_path: str = "config/customer_mapping.yaml"
    warranty_rules_path: str = "config/warranty_rules.yaml"

    # --- VBM Crawler bridge -------------------------------------------------
    # Pfad zum `output/` des Schwester-Repos KRAI-Crawler-VBM. Leer = Sibling-
    # Default (`../KRAI-Crawler-VBM/output/`). Wird von `--vbm-crawler` genutzt.
    vbm_crawler_output_dir: str = ""

    # --- Reverse-proxy basic auth (Phase 6) --------------------------------
    basic_auth_user: str = ""
    basic_auth_password: str = ""

    # ----------------------------------------------------------------------
    # Derived connection strings
    # ----------------------------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def insights_sqlalchemy_url(self) -> str:
        """SQLAlchemy URL for the Insights PostgreSQL (psycopg v3 driver)."""
        pw = quote_plus(self.insights_db_password)
        return (
            f"postgresql+psycopg://{self.insights_db_user}:{pw}"
            f"@{self.insights_db_host}:{self.insights_db_port}/{self.insights_db_name}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def krai_pg_sqlalchemy_url(self) -> str:
        """SQLAlchemy URL for the read-only KRAI PostgreSQL source."""
        pw = quote_plus(self.krai_pg_password)
        return (
            f"postgresql+psycopg://{self.krai_pg_user}:{pw}"
            f"@{self.krai_pg_host}:{self.krai_pg_port}/{self.krai_pg_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fleetmgmt_sqlalchemy_url(self) -> str:
        """SQLAlchemy URL for the read-only FleetMgmt MSSQL source (pyodbc)."""
        trust = "yes" if self.fleetmgmt_mssql_trust_cert else "no"
        odbc = (
            f"DRIVER={{{self.fleetmgmt_mssql_driver}}};"
            f"SERVER={self.fleetmgmt_mssql_host},{self.fleetmgmt_mssql_port};"
            f"DATABASE={self.fleetmgmt_mssql_db};"
            f"UID={self.fleetmgmt_mssql_user};PWD={self.fleetmgmt_mssql_password};"
            f"TrustServerCertificate={trust};Encrypt=yes;"
        )
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}"

    @property
    def is_radix_configured(self) -> bool:
        """True once all four Radix login credentials are present."""
        return all(
            [
                self.radix_username,
                self.radix_password_base64,
                self.radix_client_code,
                self.radix_license_id,
            ]
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
