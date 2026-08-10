import os

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data")

# The placeholder JWT secret. This repo is public, so a deploy that keeps it is
# trivially forgeable: anyone can sign a token for user id 1..3 (seed.py's demo
# rows, one of them `admin`) and get that role, because current_user reads the
# role from the DB row the token names. Boot refuses it unless dev_mode is on.
DEV_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    # The dotenv paths are absolute, anchored on the repo, because a relative
    # ".env" is resolved against the *current working directory* -- and every
    # Makefile target `cd backend` first, which hid the repo-root .env from all
    # of them (`make seed`, `make seed-collectors`, `make api`, the workers).
    # The symptom was the placeholder-secret guard below refusing to boot even
    # though a real NDB_JWT_SECRET was sitting in .env the whole time.
    # backend/.env is read second, so it can override the root file when present.
    model_config = SettingsConfigDict(
        env_prefix="NDB_",
        env_file=(os.path.join(REPO, ".env"), os.path.join(REPO, "backend", ".env")),
        extra="ignore",
    )

    duckdb_path: str = os.path.join(DATA, "tbia.duckdb")
    sqlite_path: str = os.path.join(DATA, "annotations.sqlite")

    # DuckDB resource caps. Defaults preserve prior local behavior (4 threads,
    # DuckDB's own ~80%-of-RAM memory limit). On a small instance (e.g. t3.small)
    # set NDB_DUCK_THREADS=2, NDB_DUCK_MEMORY_LIMIT=1GB, NDB_DUCK_TEMP_DIR=... so a
    # heavy aggregation spills to disk instead of OOM-killing the process.
    duck_threads: int = 4
    duck_memory_limit: str = ""  # e.g. "1GB"; empty -> leave DuckDB default
    duck_temp_dir: str = ""  # spill dir when memory_limit is hit; empty -> default

    # Master "this is a throwaway local environment" switch. Off by default, so
    # anything unsafe stays off unless a developer opts in explicitly. Gates the
    # placeholder jwt_secret and (together with dev_login) the password-less
    # sign-in. NEVER set this in a shared or deployed environment.
    dev_mode: bool = False

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # ── ORCID OAuth (sign-in is ORCID-only) ─────────────────────────────────
    # These read plain ORCID_* env vars (no NDB_ prefix) via validation_alias.
    # Register a client at https://orcid.org/developer-tools (any ORCID member),
    # request scope `/authenticate`, and set the redirect URI to
    # `<frontend>/auth/orcid/callback`. Swapping in an official org client later
    # is just a change of these two values (see docs) — user iDs are unaffected.
    orcid_base: str = Field(default="https://orcid.org", validation_alias="ORCID_BASE")
    orcid_client_id: str = Field(default="", validation_alias="ORCID_CLIENT_ID")
    orcid_client_secret: str = Field(default="", validation_alias="ORCID_CLIENT_SECRET")
    orcid_redirect_uri: str = Field(
        default="http://localhost:5173/auth/orcid/callback",
        validation_alias="ORCID_REDIRECT_URI",
    )
    orcid_scope: str = Field(default="/authenticate", validation_alias="ORCID_SCOPE")
    # Comma-separated ORCID iDs (0000-0000-0000-0000) granted `admin` on first
    # sign-in. Everyone else defaults to `contributor`.
    orcid_admin_ids: str = Field(default="", validation_alias="ORCID_ADMIN_IDS")

    # DEV-ONLY password-less sign-in for the seeded demo users. ORCID OAuth
    # cannot round-trip on localhost, so this lets local dev pick a role without
    # ORCID. It mints tokens ONLY for existing seeded demo users (email set) —
    # one of which is an `admin`, so on a deployed box this is a full auth
    # bypass. Never read this field directly: the endpoints check
    # `dev_login_enabled`, which also requires dev_mode, so flipping one flag by
    # itself can't open the bypass.
    dev_login: bool = False

    # Comma-separated origins allowed by CORS (the Vite dev server).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Discord webhook for "request review" pings (empty -> notifications are
    # skipped; the request is still persisted). Create one in a Discord channel
    # under Integrations → Webhooks and paste its URL. Plain env vars (no NDB_).
    discord_webhook_url: str = Field(default="", validation_alias="DISCORD_WEBHOOK_URL")

    # AI transcription pipeline (the batch worker that drains transcribe_requests
    # and calls Claude vision). ANTHROPIC_API_KEY is read by the SDK directly;
    # without it the worker skips API calls. Plain env vars (no NDB_ prefix).
    anthropic_model: str = Field(
        default="claude-opus-5", validation_alias="ANTHROPIC_MODEL"
    )
    transcribe_batch: int = Field(default=20, validation_alias="TRANSCRIBE_BATCH")
    # "single" = one Claude vision call does OCR + fields (uses anthropic_model).
    # "two_stage" = ocr_model reads the label to verbatim text, then field_model
    # (text-only) structures it into annotation fields — cheaper image tokens.
    transcribe_mode: str = Field(default="two_stage", validation_alias="TRANSCRIBE_MODE")
    ocr_model: str = Field(default="claude-sonnet-5", validation_alias="OCR_MODEL")
    field_model: str = Field(default="claude-opus-5", validation_alias="FIELD_MODEL")

    @model_validator(mode="after")
    def _refuse_insecure_defaults(self) -> "Settings":
        if self.jwt_secret == DEV_JWT_SECRET and not self.dev_mode:
            raise RuntimeError(
                "NDB_JWT_SECRET is still the placeholder from this (public) repo, "
                "so anyone could forge an admin session. Set a real one:\n"
                "    NDB_JWT_SECRET=$(openssl rand -hex 32)\n"
                "Local throwaway environment? Set NDB_DEV_MODE=true instead."
            )
        return self

    @property
    def dev_login_enabled(self) -> bool:
        """Whether the password-less demo sign-in is available. Deliberately
        needs *both* flags — see `dev_login`."""
        return self.dev_login and self.dev_mode

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.sqlite_path}"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def orcid_admin_list(self) -> list[str]:
        return [o.strip() for o in self.orcid_admin_ids.split(",") if o.strip()]

    @property
    def orcid_authorize_endpoint(self) -> str:
        return f"{self.orcid_base}/oauth/authorize"

    @property
    def orcid_token_endpoint(self) -> str:
        return f"{self.orcid_base}/oauth/token"


settings = Settings()
