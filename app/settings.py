from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    crm_base_url: str = 'https://crm.dtel.ru'
    crm_cookie: str = ''
    dry_run: bool = True
    request_timeout: int = 20
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

settings = Settings()
