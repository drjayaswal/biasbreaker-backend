from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    FRONTEND_URL: str
    DATABASE_URL: str
    ML_SERVER_URL: str
    SECRET_KEY: str
    ALGORITHM: str

    model_config = SettingsConfigDict(env_file=".env")

@lru_cache
def settings():
    return Settings()
