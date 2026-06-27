from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", validation_alias="MONGODB_URI")
    mongodb_db_name: str = Field(default="intelliflow", validation_alias="MONGODB_DB_NAME")

    llm_model: str = Field(default="llama-3.3-70b-versatile", validation_alias="LLM_MODEL")
    llm_fallback_model: str = Field(default="claude-sonnet-4-6", validation_alias="LLM_FALLBACK_MODEL")
    llm_rewriter_model: str = Field(default="claude-haiku-4-5", validation_alias="LLM_REWRITER_MODEL")
    llm_base_url: str = Field(
        default="https://api.groq.com/openai/v1", validation_alias="LLM_BASE_URL"
    )

    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", validation_alias="EMBEDDING_MODEL")
    reranker_model: str = Field(default="BAAI/bge-reranker-base", validation_alias="RERANKER_MODEL")
    rag_generator_input_token_cap: int = Field(default=15000, validation_alias="RAG_GENERATOR_INPUT_TOKEN_CAP")

    chroma_persist_dir: str = Field(default="./.chroma", validation_alias="CHROMA_PERSIST_DIR")
    kb_root: str = Field(default="./knowledge_base", validation_alias="KB_ROOT")

    rate_limit_generations_per_minute: int = 10
    rate_limit_other_per_minute: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def chroma_dir(self) -> Path:
        return Path(self.chroma_persist_dir).expanduser().resolve()

    def kb_dir(self) -> Path:
        return Path(self.kb_root).expanduser().resolve()

    def llm_api_key(self) -> str:
        """Return the key for the primary LLM provider (Groq → OpenAI fallback)."""
        return self.groq_api_key or self.openai_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
