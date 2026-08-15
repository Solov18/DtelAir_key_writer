from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    app_environment: str = "development"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    database_url: str = (
        "postgresql+psycopg://dtel:change-me@127.0.0.1:5432/dtel"
    )
    database_echo: bool = False
    database_connect_timeout: int = 5
    database_pool_size: int = 5
    database_max_overflow: int = 2
    database_pool_timeout: int = 30
    database_pool_recycle: int = 1800
    crm_base_url: str = 'https://crm.dtel.ru'
    crm_cookie: str = ''
    crm_login: str = ''
    crm_password: str = ''
    crm_buyer_id: str = ''
    dry_run: bool = True
    request_timeout: int = 20
    panel_api_login: str = ''
    panel_api_password: str = ''
    panel_api_timeout: float = 3.0
    panel_monitor_enabled: bool = True
    panel_monitor_interval_seconds: int = 300
    panel_monitor_concurrency: int = 12
    panel_monitor_stale_seconds: int = 600
    panel_manual_check_cooldown_seconds: int = 10
    session_secret: str = 'change-this-secret-key-later'
    session_https_only: bool = False
    session_max_age_seconds: int = 28800
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    @property
    def trusted_host_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]

    def validate_production(self) -> None:
        """Fail closed when production is started with unsafe defaults."""

        if self.app_environment.strip().lower() != "production":
            return
        if (
            self.session_secret == "change-this-secret-key-later"
            or len(self.session_secret) < 32
        ):
            raise RuntimeError(
                "SESSION_SECRET must be a unique random value of at least 32 characters."
            )
        if not self.session_https_only:
            raise RuntimeError("SESSION_HTTPS_ONLY must be true in production.")
        try:
            database_url = make_url(self.database_url)
        except Exception as error:
            raise RuntimeError("DATABASE_URL is not a valid SQLAlchemy URL.") from error
        database_name = (database_url.database or "").strip().lower()
        if database_url.drivername != "postgresql+psycopg":
            raise RuntimeError(
                "Production DATABASE_URL must use postgresql+psycopg."
            )
        if not database_name or "test" in database_name:
            raise RuntimeError("Production cannot use a PostgreSQL test database.")
        if not self.trusted_host_list or "*" in self.trusted_host_list:
            raise RuntimeError("TRUSTED_HOSTS must explicitly list production host names.")

settings = Settings()
