from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://dtel:change-me@127.0.0.1:5432/dtel"
    )
    database_echo: bool = False
    database_connect_timeout: int = 5
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
    session_secret: str = 'change-this-secret-key-later'
    session_https_only: bool = False
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

settings = Settings()
