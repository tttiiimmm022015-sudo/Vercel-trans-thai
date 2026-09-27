import hashlib
import logging
from threading import RLock

import httpx

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE_MODE = "th"
SUPPORTED_LANGUAGE_MODES = frozenset({"th", "vi", "en"})
KEY_PREFIX = "line-translator:language-mode"

_memory_modes: dict[str, str] = {}
_memory_lock = RLock()


class LanguageModeStoreError(RuntimeError):
    """群組語言設定無法寫入永久儲存。"""


def _storage_key(conversation_id: str) -> str:
    """以雜湊保存聊天室識別碼，避免在 Redis Key 暴露 LINE ID。"""

    digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}:{digest}"


def _has_redis_settings(settings: Settings) -> bool:
    return bool(
        settings.upstash_redis_rest_url
        and settings.upstash_redis_rest_token
    )


def _redis_command(
    command: list[str],
    settings: Settings,
) -> object:
    response = httpx.post(
        settings.upstash_redis_rest_url.rstrip("/"),
        headers={
            "Authorization": (
                f"Bearer {settings.upstash_redis_rest_token}"
            )
        },
        json=command,
        timeout=settings.language_store_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict) or payload.get("error"):
        error_name = "invalid_response"
        if isinstance(payload, dict):
            error_name = str(payload.get("error") or error_name)[:100]
        raise LanguageModeStoreError(
            f"Upstash Redis 回傳錯誤：{error_name}"
        )

    return payload.get("result")


def get_language_mode(
    conversation_id: str | None,
    settings: Settings | None = None,
) -> str:
    """取得聊天室模式；未設定的舊群組一律維持泰文模式。"""

    if not conversation_id:
        return DEFAULT_LANGUAGE_MODE

    active_settings = settings or get_settings()

    if _has_redis_settings(active_settings):
        try:
            value = _redis_command(
                ["GET", _storage_key(conversation_id)],
                active_settings,
            )
            if isinstance(value, str) and value in SUPPORTED_LANGUAGE_MODES:
                with _memory_lock:
                    _memory_modes[conversation_id] = value
                return value
        except (httpx.HTTPError, ValueError, LanguageModeStoreError):
            logger.exception("讀取群組語言設定失敗，使用安全預設值")

    with _memory_lock:
        return _memory_modes.get(
            conversation_id,
            DEFAULT_LANGUAGE_MODE,
        )


def set_language_mode(
    conversation_id: str,
    mode: str,
    settings: Settings | None = None,
) -> bool:
    """切換聊天室模式；回傳是否已成功寫入永久儲存。"""

    if not conversation_id:
        raise ValueError("缺少聊天室識別碼")
    if mode not in SUPPORTED_LANGUAGE_MODES:
        raise ValueError(f"不支援的語言模式：{mode}")

    with _memory_lock:
        _memory_modes[conversation_id] = mode

    active_settings = settings or get_settings()
    if not _has_redis_settings(active_settings):
        logger.warning(
            "未設定 Upstash Redis；語言模式只會暫存在目前執行個體"
        )
        return False

    try:
        result = _redis_command(
            ["SET", _storage_key(conversation_id), mode],
            active_settings,
        )
    except (httpx.HTTPError, ValueError, LanguageModeStoreError) as error:
        logger.exception("寫入群組語言設定失敗")
        raise LanguageModeStoreError(
            "無法永久保存群組語言設定"
        ) from error

    if result != "OK":
        raise LanguageModeStoreError(
            "Upstash Redis 未確認群組語言設定"
        )

    logger.info("群組語言模式已永久保存：mode=%s", mode)
    return True


def clear_memory_modes() -> None:
    """僅供測試清除目前執行個體的暫存。"""

    with _memory_lock:
        _memory_modes.clear()
