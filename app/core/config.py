import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-3.1-flash-lite"
DEFAULT_GEMINI_REQUEST_TIMEOUT_MS = 10000
DEFAULT_GEMINI_KEY_COOLDOWN_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 1024
MAX_NUMBERED_GEMINI_KEYS = 20


def _split_keys(value: str) -> list[str]:
    """支援逗號、分號或換行分隔的 Gemini API Keys。"""

    normalized = value.replace(";", ",").replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _load_gemini_api_keys() -> tuple[str, ...]:
    """
    讀取 Gemini API Keys，並保持向下相容。

    支援：
    - GEMINI_API_KEYS=key1,key2,key3
    - GEMINI_API_KEY
    - GEMINI_API_KEY_1 ... GEMINI_API_KEY_20
    - GEMINI_API_KEY1 ... GEMINI_API_KEY20
    """

    candidates: list[str] = []
    candidates.extend(_split_keys(os.getenv("GEMINI_API_KEYS", "")))

    legacy_key = os.getenv("GEMINI_API_KEY", "").strip()
    if legacy_key:
        candidates.append(legacy_key)

    for index in range(1, MAX_NUMBERED_GEMINI_KEYS + 1):
        for variable_name in (
            f"GEMINI_API_KEY_{index}",
            f"GEMINI_API_KEY{index}",
        ):
            api_key = os.getenv(variable_name, "").strip()
            if api_key:
                candidates.append(api_key)

    # 去除重複 Key，同時保留 Vercel 中設定的原始順序。
    return tuple(dict.fromkeys(candidates))


@dataclass(frozen=True)
class Settings:
    """應用程式環境設定。"""

    gemini_api_keys: tuple[str, ...]
    line_channel_secret: str
    line_channel_access_token: str
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_fallback_model: str = DEFAULT_GEMINI_FALLBACK_MODEL
    gemini_request_timeout_ms: int = DEFAULT_GEMINI_REQUEST_TIMEOUT_MS
    gemini_key_cooldown_seconds: float = DEFAULT_GEMINI_KEY_COOLDOWN_SECONDS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    @property
    def gemini_api_key(self) -> str:
        """保留舊程式使用 settings.gemini_api_key 的相容性。"""

        return self.gemini_api_keys[0] if self.gemini_api_keys else ""

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            gemini_api_keys=_load_gemini_api_keys(),
            line_channel_secret=os.getenv(
                "LINE_CHANNEL_SECRET", ""
            ).strip(),
            line_channel_access_token=os.getenv(
                "LINE_CHANNEL_ACCESS_TOKEN", ""
            ).strip(),
            gemini_model=(
                os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
                or DEFAULT_GEMINI_MODEL
            ),
            gemini_fallback_model=(
                os.getenv(
                    "GEMINI_FALLBACK_MODEL",
                    DEFAULT_GEMINI_FALLBACK_MODEL,
                ).strip()
                or DEFAULT_GEMINI_FALLBACK_MODEL
            ),
            gemini_request_timeout_ms=int(
                os.getenv(
                    "GEMINI_REQUEST_TIMEOUT_MS",
                    str(DEFAULT_GEMINI_REQUEST_TIMEOUT_MS),
                )
            ),
            gemini_key_cooldown_seconds=float(
                os.getenv(
                    "GEMINI_KEY_COOLDOWN_SECONDS",
                    str(DEFAULT_GEMINI_KEY_COOLDOWN_SECONDS),
                )
            ),
            max_output_tokens=int(
                os.getenv(
                    "MAX_OUTPUT_TOKENS",
                    str(DEFAULT_MAX_OUTPUT_TOKENS),
                )
            ),
            host=os.getenv("HOST", "0.0.0.0").strip(),
            port=int(os.getenv("PORT", "8080")),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        missing: list[str] = []

        if not self.gemini_api_keys:
            missing.append(
                "GEMINI_API_KEYS 或 GEMINI_API_KEY / GEMINI_API_KEY_1"
            )
        if not self.line_channel_secret:
            missing.append("LINE_CHANNEL_SECRET")
        if not self.line_channel_access_token:
            missing.append("LINE_CHANNEL_ACCESS_TOKEN")

        if missing:
            names = ", ".join(missing)
            raise RuntimeError(f"缺少必要環境變數：{names}")

        if self.gemini_request_timeout_ms <= 0:
            raise RuntimeError("GEMINI_REQUEST_TIMEOUT_MS 必須大於 0")
        if self.gemini_key_cooldown_seconds < 0:
            raise RuntimeError("GEMINI_KEY_COOLDOWN_SECONDS 不得小於 0")
        if self.max_output_tokens <= 0:
            raise RuntimeError("MAX_OUTPUT_TOKENS 必須大於 0")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """建立並快取全域設定。"""

    return Settings.from_env()
