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


class EmptyGeminiResponseError(RuntimeError):
    """Gemini 請求成功，但沒有回傳任何翻譯文字。"""


# -----------------------------
# Key 輪替狀態
# -----------------------------

_lock = threading.Lock()
_current_index = 0

# (model, key_index) -> cooldown 結束時間
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

    return (
        "404" in message
        or "NOT_FOUND" in message
    )


def _claim_available_key_index(
    key_count: int,
    model: str,
    attempted_indexes: set[int],
) -> int | None:
    """
    每次呼叫領取下一把可用 Key。

    正常情況：
    Key 0 -> Key 1 -> Key 2 -> Key 3 -> Key 4 -> Key 0

    如果某把 Key 在 cooldown，就自動跳過。
    """

    global _current_index

    if key_count <= 0:
        return None

    now = time.monotonic()

    with _lock:
        expired_states = [
            state
            for state, cooldown_until in _key_cooldowns.items()
            if cooldown_until <= now
        ]

        for state in expired_states:
            _key_cooldowns.pop(state, None)

        for offset in range(key_count):
            key_index = (
                _current_index + offset
            ) % key_count

            cooldown_state = (model, key_index)

            if key_index in attempted_indexes:
                continue

            if cooldown_state in _key_cooldowns:
                continue

            # 下一次訊息從下一把 Key 開始。
            _current_index = (
                key_index + 1
            ) % key_count

            return key_index

    return None


def _mark_key_cooldown(
    model: str,
    key_index: int,
) -> None:
    with _lock:
        _key_cooldowns[(model, key_index)] = (
            time.monotonic()
            + QUOTA_COOLDOWN_SECONDS
        )


def _build_generation_config() -> types.GenerateContentConfig:
    """Gemini Flash Lite 翻譯設定。"""

    return types.GenerateContentConfig(
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(
            thinking_level=THINKING_LEVEL,
        ),
    )


def _get_response_diagnostics(
    response: object,
) -> dict[str, object]:
    """取得空白回覆的診斷資料。"""

    candidates = (
        getattr(response, "candidates", None)
        or []
    )

    finish_reasons: list[str] = []
    candidate_part_counts: list[int] = []

    for candidate in candidates:
        finish_reason = getattr(
            candidate,
            "finish_reason",
            None,
        )

        if finish_reason is not None:
            finish_reasons.append(
                str(finish_reason)
            )

        content = getattr(
            candidate,
            "content",
            None,
        )

        parts = (
            getattr(content, "parts", None)
            or []
        )

        candidate_part_counts.append(
            len(parts)
        )

    return {
        "candidate_count": len(candidates),
        "finish_reasons": (
            finish_reasons or ["UNKNOWN"]
        ),
        "candidate_part_counts": (
            candidate_part_counts
        ),
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
    """向 Gemini 發送一次翻譯請求。"""

    started_at = time.monotonic()

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=_build_generation_config(),
    )

    elapsed_seconds = (
        time.monotonic() - started_at
    )

    translated_text = (
        getattr(response, "text", "")
        or ""
    ).strip()

    if translated_text:
        logger.info(
            (
                "Gemini API 回覆完成："
                "model=%s elapsed=%.2fs "
                "output_length=%d"
            ),
            model,
            elapsed_seconds,
            len(translated_text),
        )

        return translated_text

    diagnostics = _get_response_diagnostics(
        response
    )

    logger.warning(
        (
            "Gemini 回傳空白內容："
            "model=%s elapsed=%.2fs "
            "candidate_count=%s "
            "finish_reasons=%s "
            "candidate_part_counts=%s "
            "prompt_feedback=%s "
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
        (
            "Gemini 回傳空白內容："
            f"model={model}, "
            f"finish_reasons="
            f"{diagnostics['finish_reasons']}"
        )
    )


def _generate_with_fallback_model(
    api_keys: tuple[str, ...] | list[str],
    prompt: str,
) -> str:
    """使用備援模型翻譯。"""

    attempted_indexes: set[int] = set()
    last_error: Exception | None = None
    key_count = len(api_keys)

    while len(attempted_indexes) < key_count:
        key_index = _claim_available_key_index(
            key_count=key_count,
            model=FALLBACK_MODEL,
            attempted_indexes=attempted_indexes,
        )

        if key_index is None:
            break

        attempted_indexes.add(key_index)

        client = genai.Client(
            api_key=api_keys[key_index]
        )

        try:
            translated_text = _request_translation(
                client=client,
                model=FALLBACK_MODEL,
                prompt=prompt,
            )

            logger.info(
                (
                    "Gemini 備援翻譯完成："
                    "model=%s key_index=%d "
                    "output_length=%d"
                ),
                FALLBACK_MODEL,
                key_index,
                len(translated_text),
            )

            return translated_text

        except EmptyGeminiResponseError:
            # 空白通常不是 Key 問題，
            # 不繼續浪費時間嘗試其他 Key。
            logger.warning(
                (
                    "Gemini 備援模型回傳空白："
                    "model=%s key_index=%d"
                ),
                FALLBACK_MODEL,
                key_index,
            )
            raise

        except ServerError:
            # 503 通常是模型服務異常，
            # 換 Key 通常沒有幫助。
            logger.warning(
                (
                    "Gemini 備援模型暫時不可用："
                    "model=%s key_index=%d"
                ),
                FALLBACK_MODEL,
                key_index,
            )
            raise

        except ClientError as error:
            last_error = error

            if _is_quota_error(error):
                _mark_key_cooldown(
                    model=FALLBACK_MODEL,
                    key_index=key_index,
                )

                logger.warning(
                    (
                        "Gemini 備援 Key 額度不足，"
                        "嘗試下一把："
                        "model=%s key_index=%d "
                        "cooldown_seconds=%.0f"
                    ),
                    FALLBACK_MODEL,
                    key_index,
                    QUOTA_COOLDOWN_SECONDS,
                )
                continue

            if _is_model_unavailable_error(error):
                raise

            logger.warning(
                (
                    "Gemini 備援 Key 呼叫失敗，"
                    "嘗試下一把："
                    "model=%s key_index=%d "
                    "error=%s"
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
    """
    每則訊息輪流使用不同 Key。

    429：
        暫停該模型的該把 Key，嘗試下一把。

    空白或 503：
        直接改用備援模型。
    """

    settings = get_settings()
    api_keys = settings.gemini_api_keys
    primary_model = settings.gemini_model

    if not api_keys:
        raise RuntimeError(
            "沒有可用的 Gemini API Key"
        )

    key_count = len(api_keys)
    attempted_indexes: set[int] = set()
    last_error: Exception | None = None

    while len(attempted_indexes) < key_count:
        key_index = _claim_available_key_index(
            key_count=key_count,
            model=primary_model,
            attempted_indexes=attempted_indexes,
        )

        if key_index is None:
            break

        attempted_indexes.add(key_index)

        logger.info(
            (
                "Gemini 選擇 API Key："
                "model=%s key_index=%d "
                "attempted=%d/%d"
            ),
            primary_model,
            key_index,
            len(attempted_indexes),
            key_count,
        )

        client = genai.Client(
            api_key=api_keys[key_index]
        )

        try:
            translated_text = _request_translation(
                client=client,
                model=primary_model,
                prompt=prompt,
            )

            logger.info(
                (
                    "Gemini 翻譯完成："
                    "model=%s key_index=%d "
                    "output_length=%d"
                ),
                primary_model,
                key_index,
                len(translated_text),
            )

            return translated_text

        except EmptyGeminiResponseError:
            logger.warning(
                (
                    "Gemini 主模型回傳空白，"
                    "立即改用備援模型："
                    "primary=%s fallback=%s"
                ),
                primary_model,
                FALLBACK_MODEL,
            )

            return _generate_with_fallback_model(
                api_keys=api_keys,
                prompt=prompt,
            )

        except ServerError:
            logger.warning(
                (
                    "Gemini 主模型回傳 503，"
                    "立即改用備援模型："
                    "primary=%s fallback=%s"
                ),
                primary_model,
                FALLBACK_MODEL,
            )

            return _generate_with_fallback_model(
                api_keys=api_keys,
                prompt=prompt,
            )

        except ClientError as error:
            last_error = error

            if _is_quota_error(error):
                _mark_key_cooldown(
                    model=primary_model,
                    key_index=key_index,
                )

                logger.warning(
                    (
                        "Gemini Key 額度不足，"
                        "嘗試下一把："
                        "model=%s key_index=%d "
                        "cooldown_seconds=%.0f"
                    ),
                    primary_model,
                    key_index,
                    QUOTA_COOLDOWN_SECONDS,
                )
                continue

            if _is_model_unavailable_error(error):
                raise

            logger.warning(
                (
                    "Gemini Key 呼叫失敗，"
                    "嘗試下一把："
                    "model=%s key_index=%d "
                    "error=%s"
                ),
                primary_model,
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
            "Gemini 主模型所有 Key 暫時不可用，"
            "改用備援模型：%s"
        ),
        FALLBACK_MODEL,
    )

    return _generate_with_fallback_model(
        api_keys=api_keys,
        prompt=prompt,
    )
