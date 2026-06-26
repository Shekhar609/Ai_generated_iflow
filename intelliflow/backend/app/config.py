from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    mongodb_uri: str = Field(default="mongodb://localhost:27017", validation_alias="MONGODB_URI")
    llm_model: str = Field(default="gpt-4-turbo", validation_alias="LLM_MODEL")
    mongodb_db_name: str = Field(default="intelliflow", validation_alias="MONGODB_DB_NAME")

    rate_limit_per_minute: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
