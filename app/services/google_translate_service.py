import logging
import time

import httpx

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


class GoogleTranslateError(RuntimeError):
    """Google Apps Script 翻譯備援呼叫失敗。"""


class GoogleTranslateNotConfiguredError(GoogleTranslateError):
    """Google Apps Script 翻譯備援尚未啟用或設定不完整。"""


DIRECTION_LANGUAGE_PAIRS = {
    "TH→ZH-TW": (("th", "zh-TW"),),
    "ZH-TW→TH": (("zh-TW", "th"),),
    "EN→ZH-TW+TH": (("en", "zh-TW"), ("en", "th")),
}


def _request_translation(
    text: str,
    source: str,
    target: str,
    settings: Settings,
) -> str:
    started_at = time.monotonic()

    try:
        response = httpx.post(
            settings.google_translate_web_app_url,
            json={
                "secret": settings.google_translate_secret,
                "text": text,
                "source": source,
                "target": target,
            },
            timeout=settings.google_translate_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()

    except (httpx.HTTPError, ValueError) as error:
        elapsed_seconds = time.monotonic() - started_at
        logger.warning(
            (
                "Google Apps Script 翻譯請求失敗："
                "source=%s target=%s elapsed=%.2fs error_type=%s"
            ),
            source,
            target,
            elapsed_seconds,
            type(error).__name__,
        )
        raise GoogleTranslateError(
            "Google Apps Script 翻譯請求失敗"
        ) from error

    elapsed_seconds = time.monotonic() - started_at

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        error_name = "unknown"
        if isinstance(payload, dict):
            error_name = str(payload.get("error") or "unknown")[:100]

        logger.warning(
            (
                "Google Apps Script 翻譯拒絕請求："
                "source=%s target=%s elapsed=%.2fs error=%s"
            ),
            source,
            target,
            elapsed_seconds,
            error_name,
        )
        raise GoogleTranslateError(
            f"Google Apps Script 翻譯失敗：{error_name}"
        )

    translated_text = str(payload.get("translatedText") or "").strip()
    if not translated_text:
        logger.warning(
            (
                "Google Apps Script 回傳空白內容："
                "source=%s target=%s elapsed=%.2fs"
            ),
            source,
            target,
            elapsed_seconds,
        )
        raise GoogleTranslateError(
            "Google Apps Script 回傳空白翻譯結果"
        )

    logger.info(
        (
            "Google Apps Script 翻譯完成："
            "source=%s target=%s elapsed=%.2fs output_length=%d"
        ),
        source,
        target,
        elapsed_seconds,
        len(translated_text),
    )
    return translated_text


def translate_with_google(
    text: str,
    direction: str,
    settings: Settings | None = None,
) -> str:
    """使用 Apps Script LanguageApp 執行最後一層翻譯備援。"""

    active_settings = settings or get_settings()

    if not active_settings.google_translate_enabled:
        raise GoogleTranslateNotConfiguredError(
            "Google Apps Script 翻譯備援未啟用"
        )

    if (
        not active_settings.google_translate_web_app_url
        or not active_settings.google_translate_secret
    ):
        raise GoogleTranslateNotConfiguredError(
            "Google Apps Script 翻譯備援設定不完整"
        )

    language_pairs = DIRECTION_LANGUAGE_PAIRS.get(direction)
    if language_pairs is None:
        raise GoogleTranslateError(
            f"Google Apps Script 不支援翻譯方向：{direction}"
        )

    results = [
        _request_translation(
            text=text,
            source=source,
            target=target,
            settings=active_settings,
        )
        for source, target in language_pairs
    ]

    if direction == "EN→ZH-TW+TH":
        return f"中文：\n{results[0]}\n\n泰文：\n{results[1]}"

    return results[0]
