import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


# 本機會讀取 .env；Vercel 正式環境直接使用 Project Environment Variables。
load_dotenv()


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()

    try:
        return int(raw_value)
    except ValueError as error:
        raise RuntimeError(
            f"{name} 必須是整數，目前值為：{raw_value}"
        ) from error


def _read_gemini_api_keys() -> tuple[str, ...]:
    """
    支援：
    GEMINI_API_KEYS=key1,key2,key3

    同時相容舊版：
    GEMINI_API_KEY=key1
    """

    raw_keys = os.getenv("GEMINI_API_KEYS", "").strip()

    keys = tuple(
        key.strip()
        for key in raw_keys.split(",")
        if key.strip()
    )

    # 相容舊版 GEMINI_API_KEY
    legacy_key = os.getenv("GEMINI_API_KEY", "").strip()

    if legacy_key and legacy_key not in keys:
        keys = (*keys, legacy_key)

    return keys


@dataclass(frozen=True)
class Settings:
    """應用程式環境設定。"""

    gemini_api_keys: tuple[str, ...]
    line_channel_secret: str
    line_channel_access_token: str

    gemini_model: str = "gemini-3.1-flash-lite"

    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    max_output_tokens: int = 256

    # Key 遇到 429 後，暫停使用多久
    gemini_key_cooldown_seconds: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            gemini_api_keys=_read_gemini_api_keys(),

            line_channel_secret=os.getenv(
                "LINE_CHANNEL_SECRET",
                ""
            ).strip(),

            line_channel_access_token=os.getenv(
                "LINE_CHANNEL_ACCESS_TOKEN",
                ""
            ).strip(),

            gemini_model=os.getenv(
                "GEMINI_MODEL",
                "gemini-3.1-flash-lite"
            ).strip(),

            host=os.getenv(
                "HOST",
                "0.0.0.0"
            ).strip(),

            port=_read_int(
                "PORT",
                8080
            ),

            log_level=os.getenv(
                "LOG_LEVEL",
                "INFO"
            ).strip().upper(),

            max_output_tokens=_read_int(
                "MAX_OUTPUT_TOKENS",
                256
            ),

            gemini_key_cooldown_seconds=_read_int(
                "GEMINI_KEY_COOLDOWN_SECONDS",
                60
            ),
        )

        settings.validate()

        return settings

    def validate(self) -> None:
        missing = []

        if not self.gemini_api_keys:
            missing.append(
                "GEMINI_API_KEYS 或 GEMINI_API_KEY"
            )

        if not self.line_channel_secret:
            missing.append(
                "LINE_CHANNEL_SECRET"
            )

        if not self.line_channel_access_token:
            missing.append(
                "LINE_CHANNEL_ACCESS_TOKEN"
            )

        if missing:
            raise RuntimeError(
                f"缺少必要環境變數：{', '.join(missing)}"
            )

        if self.max_output_tokens < 1:
            raise RuntimeError(
                "MAX_OUTPUT_TOKENS 必須大於 0"
            )

        if self.gemini_key_cooldown_seconds < 0:
            raise RuntimeError(
                "GEMINI_KEY_COOLDOWN_SECONDS 不可小於 0"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """建立並快取全域設定。"""

    return Settings.from_env()
