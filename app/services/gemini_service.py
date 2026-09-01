import logging
import threading
import time

from google import genai
from google.genai.errors import ClientError, ServerError

from app.core.config import get_settings


logger = logging.getLogger(__name__)


# =========================================================
# Gemini API Key 輪詢狀態
# =========================================================

_lock = threading.Lock()

# 下一次優先使用哪一組 Key
_current_index = 0

# key index -> cooldown 結束時間
_key_cooldowns: dict[int, float] = {}


# =========================================================
# 錯誤判斷
# =========================================================

def _get_status_code(
    error: Exception
) -> int | None:
    """
    從 Google GenAI Exception 取得 HTTP Status Code。
    """

    code = getattr(
        error,
        "code",
        None,
    )

    if isinstance(code, int):
        return code

    return None


def _is_quota_error(
    error: Exception
) -> bool:
    """
    判斷是否為 429 / RESOURCE_EXHAUSTED / quota。
    """

    status_code = _get_status_code(
        error
    )

    if status_code == 429:
        return True

    message = str(error).lower()

    return (
        "429" in message
        or "resource_exhausted" in message
        or "quota" in message
    )


def _is_temporary_server_error(
    error: Exception
) -> bool:
    """
    Gemini 暫時性的伺服器錯誤。

    這種錯誤不是 API Key 本身有問題，
    所以不應該讓 Key 進 cooldown。
    """

    status_code = _get_status_code(
        error
    )

    return status_code in {
        500,
        502,
        503,
        504,
    }


# =========================================================
# Key 輪詢
# =========================================================

def _get_available_key_indexes(
    key_count: int
) -> list[int]:
    """
    取得目前沒有在 cooldown 的 Key。

    順序從 _current_index 開始。
    """

    global _current_index

    now = time.monotonic()

    with _lock:

        # 清除已過期 cooldown
        expired_indexes = [
            index
            for index, cooldown_until
            in _key_cooldowns.items()
            if cooldown_until <= now
        ]

        for index in expired_indexes:
            _key_cooldowns.pop(
                index,
                None,
            )

        indexes = []

        # 從目前輪詢位置開始
        for offset in range(
            key_count
        ):
            index = (
                _current_index
                + offset
            ) % key_count

            if index not in _key_cooldowns:
                indexes.append(
                    index
                )

        return indexes


def _advance_index(
    used_index: int,
    key_count: int,
) -> None:
    """
    成功使用一組 Key 後，
    下一次從下一組 Key 開始。
    """

    global _current_index

    with _lock:
        _current_index = (
            used_index + 1
        ) % key_count


def _put_key_in_cooldown(
    index: int
) -> None:
    """
    將指定 API Key 暫時放入 cooldown。

    主要用於 429 額度 / Rate Limit。
    """

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
        "Gemini API Key #%d "
        "進入 cooldown %d 秒",
        index + 1,
        cooldown_seconds,
    )


# =========================================================
# Gemini API 呼叫
# =========================================================

def _generate_with_key(
    api_key: str,
    prompt: str,
) -> str:
    """
    使用指定 Gemini API Key 呼叫模型。
    """

    settings = get_settings()

    client = genai.Client(
        api_key=api_key
    )

    response = (
        client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config={
                "temperature": 0,
                "max_output_tokens":
                    settings.max_output_tokens,
            },
        )
    )

    return (
        response.text
        or ""
    ).strip()


# =========================================================
# 翻譯主程式
# =========================================================

def generate_translation(
    prompt: str
) -> str:
    """
    使用多組 Gemini API Key。

    行為：

    成功：
        回傳翻譯結果，
        下一次從下一組 Key 開始。

    429：
        API Key 進 cooldown，
        自動嘗試下一組 Key。

    500 / 502 / 503 / 504：
        Gemini 服務暫時異常，
        不讓 Key 進 cooldown，
        自動嘗試下一組 Key。

    其他 4xx：
        直接拋給上層處理。

    其他未知錯誤：
        記錄完整錯誤後拋給上層。
    """

    settings = get_settings()

    api_keys = (
        settings.gemini_api_keys
    )

    key_count = len(
        api_keys
    )

    if key_count == 0:
        raise RuntimeError(
            "未設定 Gemini API Key"
        )

    indexes = (
        _get_available_key_indexes(
            key_count
        )
    )

    # 如果全部 Key 都在 cooldown，
    # 允許重新全部嘗試一次
    if not indexes:
        logger.warning(
            "所有 Gemini API Key "
            "目前都在 cooldown，"
            "重新嘗試全部 Key"
        )

        indexes = list(
            range(key_count)
        )

    last_quota_error = None
    last_server_error = None

    for index in indexes:

        api_key = (
            api_keys[index]
        )

        started_at = (
            time.perf_counter()
        )

        try:

            translated_text = (
                _generate_with_key(
                    api_key,
                    prompt,
                )
            )

            elapsed = (
                time.perf_counter()
                - started_at
            )

            logger.info(
                "Gemini 回應完成："
                "key=%d/%d "
                "model=%s "
                "elapsed=%.2fs",
                index + 1,
                key_count,
                settings.gemini_model,
                elapsed,
            )

            # 下一次從下一組 Key 開始
            _advance_index(
                index,
                key_count,
            )

            return translated_text

        # -------------------------------------------------
        # 4xx
        # -------------------------------------------------

        except ClientError as error:

            elapsed = (
                time.perf_counter()
                - started_at
            )

            status_code = (
                _get_status_code(
                    error
                )
            )

            # 429
            if _is_quota_error(
                error
            ):
                last_quota_error = (
                    error
                )

                logger.warning(
                    "Gemini Key #%d/%d "
                    "遇到額度限制 "
                    "(status=%s) "
                    "elapsed=%.2fs，"
                    "嘗試下一組 Key",
                    index + 1,
                    key_count,
                    status_code,
                    elapsed,
                )

                _put_key_in_cooldown(
                    index
                )

                continue

            # 非 429 ClientError
            logger.error(
                "Gemini Key #%d/%d "
                "發生 ClientError："
                "status=%s "
                "error=%s "
                "elapsed=%.2fs",
                index + 1,
                key_count,
                status_code,
                error,
                elapsed,
            )

            raise

        # -------------------------------------------------
        # 5xx
        # -------------------------------------------------

        except ServerError as error:

            elapsed = (
                time.perf_counter()
                - started_at
            )

            status_code = (
                _get_status_code(
                    error
                )
            )

            if _is_temporary_server_error(
                error
            ):
                last_server_error = (
                    error
                )

                logger.warning(
                    "Gemini Key #%d/%d "
                    "服務暫時異常 "
                    "(status=%s) "
                    "elapsed=%.2fs，"
                    "嘗試下一組 Key",
                    index + 1,
                    key_count,
                    status_code,
                    elapsed,
                )

                # 重要：
                # 5xx 不是 Key 額度問題
                # 所以不要 cooldown
                continue

            logger.exception(
                "Gemini Key #%d/%d "
                "發生 ServerError："
                "status=%s "
                "elapsed=%.2fs",
                index + 1,
                key_count,
                status_code,
                elapsed,
            )

            raise

        # -------------------------------------------------
        # 未知錯誤
        # -------------------------------------------------

        except Exception as error:

            elapsed = (
                time.perf_counter()
                - started_at
            )

            logger.exception(
                "Gemini Key #%d/%d "
                "發生未知錯誤："
                "type=%s "
                "error=%r "
                "elapsed=%.2fs",
                index + 1,
                key_count,
                type(error).__name__,
                error,
                elapsed,
            )

            raise

    # =====================================================
    # 所有 Key 都失敗
    # =====================================================

    if last_quota_error is not None:
        logger.error(
            "所有可使用的 Gemini API Key "
            "皆遇到額度限制"
        )

        raise last_quota_error

    if last_server_error is not None:
        logger.error(
            "所有可使用的 Gemini API Key "
            "皆遇到 Gemini 暫時性服務錯誤"
        )

        raise last_server_error

    raise RuntimeError(
        "目前沒有可使用的 Gemini API Key"
    )
