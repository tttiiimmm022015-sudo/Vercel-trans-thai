import logging
import threading
import time

import httpx
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)
THINKING_LEVEL = "minimal"


class EmptyGeminiResponseError(RuntimeError):
    """Gemini 請求成功，但沒有回傳任何翻譯文字。"""


class GeminiRequestTimeoutError(RuntimeError):
    """Gemini 請求超過設定的等待時間。"""


class NoAvailableGeminiKeyError(RuntimeError):
    """指定模型目前沒有可用的 API Key。"""


_lock = threading.Lock()

# (model, key_index) -> cooldown 結束時間。
# 此狀態只用於目前 Vercel instance；每次請求仍會自行嘗試其他 Key。
_key_cooldowns: dict[tuple[str, int], float] = {}


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


def _get_available_key_indexes(
    key_count: int,
    model: str,
) -> list[int]:
    """依照設定順序取得目前可用的 API Key。"""

    if key_count <= 0:
        return []

    now = time.monotonic()

    with _lock:
        expired_states = [
            state
            for state, cooldown_until in _key_cooldowns.items()
            if cooldown_until <= now
        ]

        for state in expired_states:
            _key_cooldowns.pop(state, None)

        indexes = [
            index
            for index in range(key_count)
            if (model, index) not in _key_cooldowns
        ]

    return indexes


def _mark_key_cooldown(
    model: str,
    key_index: int,
    cooldown_seconds: float,
) -> None:
    with _lock:
        _key_cooldowns[(model, key_index)] = (
            time.monotonic() + cooldown_seconds
        )


def _build_client(
    api_key: str,
    timeout_ms: int,
) -> genai.Client:
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )


def _build_generation_config(
    settings: Settings,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        max_output_tokens=settings.max_output_tokens,
        thinking_config=types.ThinkingConfig(
            thinking_level=THINKING_LEVEL,
        ),
    )


def _get_response_diagnostics(
    response: object,
) -> dict[str, object]:
    candidates = getattr(response, "candidates", None) or []
    finish_reasons: list[str] = []
    candidate_part_counts: list[int] = []

    for candidate in candidates:
        finish_reason = getattr(candidate, "finish_reason", None)

        if finish_reason is not None:
            finish_reasons.append(str(finish_reason))

        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        candidate_part_counts.append(len(parts))

    return {
        "candidate_count": len(candidates),
        "finish_reasons": finish_reasons or ["UNKNOWN"],
        "candidate_part_counts": candidate_part_counts,
        "prompt_feedback": getattr(response, "prompt_feedback", None),
        "usage_metadata": getattr(response, "usage_metadata", None),
    }


def _request_translation(
    client: genai.Client,
    model: str,
    prompt: str,
    settings: Settings,
) -> str:
    """發送一次請求；不重試同一個慢請求。"""

    started_at = time.monotonic()

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=_build_generation_config(settings),
        )

    except httpx.TimeoutException as error:
        elapsed_seconds = time.monotonic() - started_at

        logger.warning(
            "Gemini 請求逾時：model=%s elapsed=%.2fs timeout_ms=%d",
            model,
            elapsed_seconds,
            settings.gemini_request_timeout_ms,
        )

        raise GeminiRequestTimeoutError(
            f"Gemini 請求超過 "
            f"{settings.gemini_request_timeout_ms}ms"
        ) from error

    elapsed_seconds = time.monotonic() - started_at
    translated_text = (
        getattr(response, "text", "") or ""
    ).strip()

    if translated_text:
        logger.info(
            (
                "Gemini API 回覆完成："
                "model=%s elapsed=%.2fs output_length=%d"
            ),
            model,
            elapsed_seconds,
            len(translated_text),
        )
        return translated_text

    diagnostics = _get_response_diagnostics(response)

    logger.warning(
        (
            "Gemini 回傳空白內容：model=%s elapsed=%.2fs "
            "candidate_count=%s finish_reasons=%s "
            "candidate_part_counts=%s prompt_feedback=%s "
            "usage_metadata=%s"
        ),
        model,
        elapsed_seconds,
        diagnostics["candidate_count"],
        diagnostics["finish_reasons"],
        diagnostics["candidate_part_counts"],
        diagnostics["prompt_feedback"],
        diagnostics["usage_metadata"],
    )

    raise EmptyGeminiResponseError(
        f"Gemini 回傳空白內容：model={model}, "
        f"finish_reasons={diagnostics['finish_reasons']}"
    )


def _generate_with_model(
    api_keys: tuple[str, ...],
    model: str,
    prompt: str,
    settings: Settings,
) -> str:
    """使用指定模型；429 換 Key，暫時性錯誤最多換 Key 重試一次。"""

    last_error: Exception | None = None
    transient_retry_count = 0

    indexes = _get_available_key_indexes(
        len(api_keys),
        model,
    )

    for attempt, key_index in enumerate(indexes, start=1):
        logger.info(
            (
                "Gemini 選擇 API Key："
                "model=%s key_index=%d attempt=%d/%d"
            ),
            model,
            key_index,
            attempt,
            len(indexes),
        )

        client = _build_client(
            api_key=api_keys[key_index],
            timeout_ms=settings.gemini_request_timeout_ms,
        )

        try:
            return _request_translation(
                client=client,
                model=model,
                prompt=prompt,
                settings=settings,
            )

        except (
            ServerError,
            GeminiRequestTimeoutError,
        ) as error:
            last_error = error

            # 503、504 或逾時只換下一把 Key 重試一次，
            # 避免嘗試全部 Key 導致 LINE 等待過久。
            if transient_retry_count >= 1:
                raise

            transient_retry_count += 1

            logger.warning(
                (
                    "Gemini 服務暫時不穩，換下一把 Key 重試："
                    "model=%s key_index=%d retry=%d/1 error=%s"
                ),
                model,
                key_index,
                transient_retry_count,
                error,
            )
            continue

        except ClientError as error:
            last_error = error

            if _is_quota_error(error):
                _mark_key_cooldown(
                    model=model,
                    key_index=key_index,
                    cooldown_seconds=(
                        settings.gemini_key_cooldown_seconds
                    ),
                )

                logger.warning(
                    (
                        "Gemini Key 額度不足，嘗試下一把："
                        "model=%s key_index=%d "
                        "cooldown_seconds=%.0f"
                    ),
                    model,
                    key_index,
                    settings.gemini_key_cooldown_seconds,
                )
                continue

            if _is_model_unavailable_error(error):
                raise

            logger.warning(
                (
                    "Gemini Key 呼叫失敗，嘗試下一把："
                    "model=%s key_index=%d error=%s"
                ),
                model,
                key_index,
                error,
            )
            continue

    if last_error is not None:
        raise last_error

    raise NoAvailableGeminiKeyError(
        f"Gemini 模型沒有可用的 API Key：{model}"
    )


def generate_translation(prompt: str) -> str:
    """依序使用 Key；暫時性錯誤重試一次後改用備援模型。"""

    settings = get_settings()
    api_keys = settings.gemini_api_keys

    if not api_keys:
        raise RuntimeError("沒有可用的 Gemini API Key")

    try:
        return _generate_with_model(
            api_keys=api_keys,
            model=settings.gemini_model,
            prompt=prompt,
            settings=settings,
        )

    except (
        EmptyGeminiResponseError,
        ServerError,
        GeminiRequestTimeoutError,
        NoAvailableGeminiKeyError,
    ):
        if (
            settings.gemini_fallback_model
            == settings.gemini_model
        ):
            raise

        logger.warning(
            (
                "Gemini 主模型失敗，改用備援模型："
                "primary=%s fallback=%s"
            ),
            settings.gemini_model,
            settings.gemini_fallback_model,
        )

        return _generate_with_model(
            api_keys=api_keys,
            model=settings.gemini_fallback_model,
            prompt=prompt,
            settings=settings,
        )

    except ClientError as error:
        if not _is_quota_error(error):
            raise

        if (
            settings.gemini_fallback_model
            == settings.gemini_model
        ):
            raise

        logger.warning(
            (
                "Gemini 主模型所有 Key 額度不足，"
                "改用備援模型：%s"
            ),
            settings.gemini_fallback_model,
        )

        return _generate_with_model(
            api_keys=api_keys,
            model=settings.gemini_fallback_model,
            prompt=prompt,
            settings=settings,
        )
