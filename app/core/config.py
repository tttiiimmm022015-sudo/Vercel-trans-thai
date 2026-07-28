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
        raise RuntimeError(f"{name} 必須是整數，目前值為：{raw_value}") from error


@dataclass(frozen=True)
class Settings:
    """應用程式環境設定。"""

    gemini_api_key: str
    line_channel_secret: str
    line_channel_access_token: str
    gemini_model: str = "gemini-3.1-flash-lite"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    max_output_tokens: int = 256

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            line_channel_secret=os.getenv("LINE_CHANNEL_SECRET", "").strip(),
            line_channel_access_token=os.getenv(
                "LINE_CHANNEL_ACCESS_TOKEN", ""
            ).strip(),
            gemini_model=os.getenv(
                "GEMINI_MODEL", "gemini-3.1-flash-lite"
            ).strip(),
            host=os.getenv("HOST", "0.0.0.0").strip(),
            port=_read_int("PORT", 8080),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            max_output_tokens=_read_int("MAX_OUTPUT_TOKENS", 256),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        missing = []

        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.line_channel_secret:
            missing.append("LINE_CHANNEL_SECRET")
        if not self.line_channel_access_token:
            missing.append("LINE_CHANNEL_ACCESS_TOKEN")

        if missing:
            raise RuntimeError(f"缺少必要環境變數：{', '.join(missing)}")

        if self.max_output_tokens < 1:
            raise RuntimeError("MAX_OUTPUT_TOKENS 必須大於 0")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """建立並快取全域設定。"""

    return Settings.from_env()
