import logging
import threading
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from app.core.config import get_settings


logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 1024
THINKING_LEVEL = "low"
QUOTA_COOLDOWN_SECONDS = 60.0

# -----------------------------
# Key 輪詢狀態
# -----------------------------

_lock = threading.Lock()
_current_index = 0

# key index -> cooldown 結束時間
_key_cooldowns: dict[int, float] = {}


def _is_quota_error(error: Exception) -> bool:
    message = str(error)
    return (
        "429" in message
        or "RESOURCE_EXHAUSTED" in message
        or "quota" in message.lower()
    )


def _is_model_unavailable_error(error: Exception) -> bool:
    message = str(error)
    return "404" in message or "NOT_FOUND" in message


def _get_available_key_indexes(key_count: int) -> list[int]:
    """從下一把 Key 開始輪詢，暫時跳過仍在 cooldown 的 Key。"""

    global _current_index

    if key_count <= 0:
        return []

    now = time.monotonic()

    with _lock:
        expired_indexes = [
            index
            for index, cooldown_until in _key_cooldowns.items()
            if cooldown_until <= now
        ]
        for index in expired_indexes:
            _key_cooldowns.pop(index, None)

        ordered_indexes = [
            (_current_index + offset) % key_count
            for offset in range(key_count)
        ]
        available_indexes = [
            index
            for index in ordered_indexes
            if index not in _key_cooldowns
        ]

        # 正常情況下，每次請求由下一把 Key 開始。
        if available_indexes:
            _current_index = (available_indexes[0] + 1) % key_count
            return available_indexes

        # 全部都在 cooldown 時不阻塞 Vercel Function；選最早恢復者試一次。
        earliest_index = min(
            range(key_count),
            key=lambda index: _key_cooldowns.get(index, now),
        )
        _current_index = (earliest_index + 1) % key_count
        return [earliest_index]


def _mark_key_cooldown(key_index: int) -> None:
    with _lock:
        _key_cooldowns[key_index] = (
            time.monotonic() + QUOTA_COOLDOWN_SECONDS
        )


def _build_generation_config() -> types.GenerateContentConfig:
    """3.5 Flash 翻譯設定：低思考兼顧速度，並預留思考 Token。"""

    return types.GenerateContentConfig(
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(
            thinking_level=THINKING_LEVEL,
        ),
    )


def generate_translation(prompt: str) -> str:
    """使用多組 API Key 輪詢呼叫 Gemini，回傳純文字翻譯。"""

    settings = get_settings()
    api_keys = settings.gemini_api_keys

    if not api_keys:
        raise RuntimeError("沒有可用的 Gemini API Key")

    last_error: Exception | None = None

    for key_index in _get_available_key_indexes(len(api_keys)):
        try:
            client = genai.Client(api_key=api_keys[key_index])
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=_build_generation_config(),
            )

            translated_text = (getattr(response, "text", "") or "").strip()
            logger.info(
                "Gemini 翻譯完成：model=%s key_index=%d output_length=%d",
                settings.gemini_model,
                key_index,
                len(translated_text),
            )
            return translated_text

        except ClientError as error:
            last_error = error

            if _is_quota_error(error):
                _mark_key_cooldown(key_index)
                logger.warning(
                    "Gemini Key 進入 cooldown：key_index=%d seconds=%.0f",
                    key_index,
                    QUOTA_COOLDOWN_SECONDS,
                )
                continue

            # 模型名稱錯誤與 Key 無關，不必把所有 Key 都試一遍。
            if _is_model_unavailable_error(error):
                raise

            logger.warning(
                "Gemini Key 呼叫失敗，嘗試下一把：key_index=%d error=%s",
                key_index,
                error,
            )
            continue

    if last_error is not None:
        raise last_error

    raise RuntimeError("目前沒有可用的 Gemini API Key")
