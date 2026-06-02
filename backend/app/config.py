import os

from pydantic_settings import BaseSettings, SettingsConfigDict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NDB_", env_file=".env", extra="ignore")

    duckdb_path: str = os.path.join(DATA, "occurrences.duckdb")
    sqlite_path: str = os.path.join(DATA, "annotations.sqlite")

    # DuckDB resource caps. Defaults preserve prior local behavior (4 threads,
    # DuckDB's own ~80%-of-RAM memory limit). On a small instance (e.g. t3.small)
    # set NDB_DUCK_THREADS=2, NDB_DUCK_MEMORY_LIMIT=1GB, NDB_DUCK_TEMP_DIR=... so a
    # heavy aggregation spills to disk instead of OOM-killing the process.
    duck_threads: int = 4
    duck_memory_limit: str = ""  # e.g. "1GB"; empty -> leave DuckDB default
    duck_temp_dir: str = ""  # spill dir when memory_limit is hit; empty -> default

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Comma-separated origins allowed by CORS (the Vite dev server).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.sqlite_path}"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
