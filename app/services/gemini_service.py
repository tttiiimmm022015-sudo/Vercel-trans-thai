import logging
import threading
import time

from google import genai
from google.genai.errors import ClientError

from app.core.config import get_settings


logger = logging.getLogger(__name__)


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


def _get_available_key_indexes(
    key_count: int
) -> list[int]:

    global _current_index

    now = time.monotonic()

    with _lock:

        # 清掉已經過期的 cooldown
        expired_indexes = [
            index
            for index, cooldown_until
            in _key_cooldowns.items()
            if cooldown_until <= now
        ]

        for index in expired_indexes:
            _key_cooldowns.pop(
                index,
                None
            )

        indexes = []

        # 從目前輪詢位置開始
        for offset in range(key_count):

            index = (
                _current_index + offset
            ) % key_count

            if index not in _key_cooldowns:
                indexes.append(index)

        return indexes


def _advance_index(
    used_index: int,
    key_count: int
) -> None:

    global _current_index

    with _lock:

        _current_index = (
            used_index + 1
        ) % key_count


def _put_key_in_cooldown(
    index: int
) -> None:

    settings = get_settings()

    cooldown_seconds = (
        settings.gemini_key_cooldown_seconds
    )

    with _lock:

        _key_cooldowns[index] = (
            time.monotonic()
            + cooldown_seconds
        )

    logger.warning(
        "Gemini API Key #%d 進入 cooldown %d 秒",
        index + 1,
        cooldown_seconds,
    )


def _generate_with_key(
    api_key: str,
    prompt: str
) -> str:

    settings = get_settings()

    client = genai.Client(
        api_key=api_key
    )

    response = client.models.generate_content(

        model=settings.gemini_model,

        contents=prompt,

        config={
            "temperature": 0,
            "max_output_tokens":
                settings.max_output_tokens,
        },
    )

    return (
        response.text or ""
    ).strip()


def generate_translation(
    prompt: str
) -> str:
    """
    使用多組 Gemini API Key。

    成功：
        下一次從下一個 Key 開始。

    429：
        該 Key 進 cooldown，
        自動嘗試下一組 Key。

    全部 Key 429：
        將最後一個 429 丟回上層處理。
    """

    settings = get_settings()

    api_keys = settings.gemini_api_keys

    key_count = len(api_keys)

    indexes = _get_available_key_indexes(
        key_count
    )

    # 如果全部都還在 cooldown，
    # 重新允許全部嘗試一次
    if not indexes:

        indexes = list(
            range(key_count)
        )

    last_quota_error = None

    for index in indexes:

        api_key = api_keys[index]

        started_at = time.perf_counter()

        try:

            translated_text = (
                _generate_with_key(
                    api_key,
                    prompt
                )
            )

            elapsed = (
                time.perf_counter()
                - started_at
            )

            logger.info(
                "Gemini 回應完成："
                "key=%d/%d model=%s elapsed=%.2fs",
                index + 1,
                key_count,
                settings.gemini_model,
                elapsed,
            )

            _advance_index(
                index,
                key_count
            )

            return translated_text

        except ClientError as error:

            if _is_quota_error(error):

                last_quota_error = error

                logger.warning(
                    "Gemini Key #%d 額度限制，嘗試下一組",
                    index + 1,
                )

                _put_key_in_cooldown(
                    index
                )

                continue

            # 不是額度錯誤
            # 直接交給上層原有錯誤處理
            raise

        except Exception:

            logger.exception(
                "Gemini Key #%d 發生未知錯誤",
                index + 1,
            )

            raise

    # 所有 Key 都遇到額度限制
    if last_quota_error:
        raise last_quota_error

    raise RuntimeError(
        "目前沒有可使用的 Gemini API Key"
    )
