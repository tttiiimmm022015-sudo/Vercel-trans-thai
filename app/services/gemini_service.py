import logging
import threading
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from app.core.config import get_settings


logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 1024
THINKING_LEVEL = "minimal"
QUOTA_COOLDOWN_SECONDS = 60.0
FALLBACK_MODEL = "gemini-3.1-flash-lite"

# 第一次立即呼叫；遇到 503 或空白回覆，0.5 秒後再試一次。
SERVER_RETRY_DELAYS = (0.0, 0.5)


class EmptyGeminiResponseError(RuntimeError):
    """Gemini 請求成功，但沒有回傳任何翻譯文字。"""


# -----------------------------
# Key 使用狀態
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

    return (
        "404" in message
        or "NOT_FOUND" in message
    )


def _get_available_key_indexes(key_count: int) -> list[int]:
    """目前 Key 優先；只有失敗時才依設定順序嘗試後續 Key。"""

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

        # 不在這裡移動索引：成功後繼續使用同一把 Key。
        if available_indexes:
            return available_indexes

        # 全部都在 cooldown 時，直接交給備援模型。
        return []


def _mark_key_cooldown(key_index: int) -> None:
    with _lock:
        _key_cooldowns[key_index] = (
            time.monotonic() + QUOTA_COOLDOWN_SECONDS
        )


def _switch_to_next_key(
    key_index: int,
    key_count: int,
) -> None:
    """目前 Key 額度用完後，才固定切換到下一把 Key。"""

    global _current_index

    with _lock:
        _current_index = (key_index + 1) % key_count


def _build_generation_config() -> types.GenerateContentConfig:
    """Gemini Flash 翻譯設定：低思考兼顧速度。"""

    return types.GenerateContentConfig(
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(
            thinking_level=THINKING_LEVEL,
        ),
    )


def _get_response_diagnostics(response: object) -> dict[str, object]:
    """擷取空白回覆的診斷資訊，避免直接記錄完整回覆內容。"""

    candidates = getattr(response, "candidates", None) or []

    finish_reasons: list[str] = []
    candidate_part_counts: list[int] = []

    for candidate in candidates:
        finish_reason = getattr(
            candidate,
            "finish_reason",
            None,
        )

        if finish_reason is not None:
            finish_reasons.append(str(finish_reason))

        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []

        candidate_part_counts.append(len(parts))

    return {
        "candidate_count": len(candidates),
        "finish_reasons": finish_reasons or ["UNKNOWN"],
        "candidate_part_counts": candidate_part_counts,
        "prompt_feedback": getattr(
            response,
            "prompt_feedback",
            None,
        ),
        "usage_metadata": getattr(
            response,
            "usage_metadata",
            None,
        ),
    }


def _request_translation(
    client: genai.Client,
    model: str,
    prompt: str,
) -> str:
    """向 Gemini 發送翻譯請求，空白回覆視為錯誤。"""

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=_build_generation_config(),
    )

    translated_text = (
        getattr(response, "text", "") or ""
    ).strip()

    if translated_text:
        return translated_text

    diagnostics = _get_response_diagnostics(response)

    logger.warning(
        (
            "Gemini 回傳空白內容：model=%s "
            "candidate_count=%s "
            "finish_reasons=%s "
            "candidate_part_counts=%s "
            "prompt_feedback=%s "
            "usage_metadata=%s"
        ),
        model,
        diagnostics["candidate_count"],
        diagnostics["finish_reasons"],
        diagnostics["candidate_part_counts"],
        diagnostics["prompt_feedback"],
        diagnostics["usage_metadata"],
    )

    raise EmptyGeminiResponseError(
        (
            "Gemini 回傳空白內容："
            f"model={model}, "
            f"finish_reasons={diagnostics['finish_reasons']}"
        )
    )


def _generate_with_server_retry(
    client: genai.Client,
    model: str,
    prompt: str,
) -> str:
    """遇到 503 或空白內容時，短暫退避後重試。"""

    last_error: Exception | None = None
    attempt_count = len(SERVER_RETRY_DELAYS)

    for attempt, delay_seconds in enumerate(
        SERVER_RETRY_DELAYS,
        start=1,
    ):
        if delay_seconds > 0:
            time.sleep(delay_seconds)

        try:
            return _request_translation(
                client=client,
                model=model,
                prompt=prompt,
            )

        except ServerError as error:
            last_error = error

            logger.warning(
                (
                    "Gemini 服務暫時不可用："
                    "model=%s attempt=%d/%d error=%s"
                ),
                model,
                attempt,
                attempt_count,
                error,
            )

        except EmptyGeminiResponseError as error:
            last_error = error

            logger.warning(
                (
                    "Gemini 回傳空白，準備重試："
                    "model=%s attempt=%d/%d error=%s"
                ),
                model,
                attempt,
                attempt_count,
                error,
            )

    if last_error is not None:
        raise last_error

    raise RuntimeError("Gemini 服務重試失敗")


def _generate_with_fallback_model(
    api_keys: tuple[str, ...] | list[str],
    prompt: str,
) -> str:
    """主模型失敗時，使用備援模型逐一嘗試 API Key。"""

    last_error: Exception | None = None

    for key_index, api_key in enumerate(api_keys):
        client = genai.Client(api_key=api_key)

        try:
            fallback_text = _generate_with_server_retry(
                client=client,
                model=FALLBACK_MODEL,
                prompt=prompt,
            )

            logger.info(
                (
                    "Gemini 備援翻譯完成："
                    "model=%s key_index=%d output_length=%d"
                ),
                FALLBACK_MODEL,
                key_index,
                len(fallback_text),
            )

            return fallback_text

        except EmptyGeminiResponseError as error:
            last_error = error

            logger.warning(
                (
                    "Gemini 備援模型回傳空白："
                    "model=%s key_index=%d error=%s"
                ),
                FALLBACK_MODEL,
                key_index,
                error,
            )

            # 空白通常不是 Key 問題，但可再嘗試下一把 Key。
            continue

        except ClientError as error:
            last_error = error

            if _is_quota_error(error):
                logger.warning(
                    (
                        "Gemini 備援模型額度不足："
                        "model=%s key_index=%d"
                    ),
                    FALLBACK_MODEL,
                    key_index,
                )
                continue

            if _is_model_unavailable_error(error):
                raise

            logger.warning(
                (
                    "Gemini 備援 Key 呼叫失敗："
                    "model=%s key_index=%d error=%s"
                ),
                FALLBACK_MODEL,
                key_index,
                error,
            )
            continue

        except ServerError as error:
            last_error = error

            logger.warning(
                (
                    "Gemini 備援模型暫時不可用："
                    "model=%s key_index=%d error=%s"
                ),
                FALLBACK_MODEL,
                key_index,
                error,
            )
            continue

    if last_error is not None:
        raise last_error

    raise RuntimeError(
        "Gemini 備援模型沒有可用的 API Key"
    )


def generate_translation(prompt: str) -> str:
    """固定使用目前 Key；額度用完後才切換下一把 Key。"""

    settings = get_settings()
    api_keys = settings.gemini_api_keys

    if not api_keys:
        raise RuntimeError("沒有可用的 Gemini API Key")

    last_error: Exception | None = None
    available_key_indexes = _get_available_key_indexes(
        len(api_keys)
    )

    for key_index in available_key_indexes:
        try:
            client = genai.Client(
                api_key=api_keys[key_index]
            )

            translated_text = _generate_with_server_retry(
                client=client,
                model=settings.gemini_model,
                prompt=prompt,
            )

            logger.info(
                (
                    "Gemini 翻譯完成："
                    "model=%s key_index=%d output_length=%d"
                ),
                settings.gemini_model,
                key_index,
                len(translated_text),
            )

            return translated_text

        except EmptyGeminiResponseError:
            logger.warning(
                (
                    "Gemini 主模型連續回傳空白，"
                    "改用備援模型：primary=%s fallback=%s"
                ),
                settings.gemini_model,
                FALLBACK_MODEL,
            )

            return _generate_with_fallback_model(
                api_keys=api_keys,
                prompt=prompt,
            )

        except ServerError:
            logger.warning(
                (
                    "Gemini 主模型連續回傳 503，"
                    "改用備援模型：primary=%s fallback=%s"
                ),
                settings.gemini_model,
                FALLBACK_MODEL,
            )

            return _generate_with_fallback_model(
                api_keys=api_keys,
                prompt=prompt,
            )

        except ClientError as error:
            last_error = error

            if _is_quota_error(error):
                _mark_key_cooldown(key_index)
                _switch_to_next_key(
                    key_index,
                    len(api_keys),
                )

                logger.warning(
                    (
                        "Gemini Key 額度不足，切換下一把："
                        "key_index=%d next_key_index=%d "
                        "cooldown_seconds=%.0f"
                    ),
                    key_index,
                    (key_index + 1) % len(api_keys),
                    QUOTA_COOLDOWN_SECONDS,
                )
                continue

            # 模型名稱錯誤與 Key 無關，
            # 不需要把全部 Key 都試一遍。
            if _is_model_unavailable_error(error):
                raise

            logger.warning(
                (
                    "Gemini Key 呼叫失敗，嘗試下一把："
                    "key_index=%d error=%s"
                ),
                key_index,
                error,
            )
            continue

    if (
        last_error is not None
        and not _is_quota_error(last_error)
    ):
        raise last_error

    logger.warning(
        (
            "Gemini 主模型沒有可用 Key，"
            "改用備援模型：%s"
        ),
        FALLBACK_MODEL,
    )

    return _generate_with_fallback_model(
        api_keys=api_keys,
        prompt=prompt,
    )
