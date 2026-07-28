import logging

from google.genai.errors import ClientError

from app.prompts.translation_prompt import build_translation_prompt
from app.services.gemini_service import generate_translation


logger = logging.getLogger(__name__)

EMPTY_TEXT_MESSAGE = "⚠️ 請輸入需要翻譯的內容。"
TRANSLATION_FAILED_MESSAGE = "⚠️ 翻譯失敗，請稍後再試。"
QUOTA_EXCEEDED_MESSAGE = "⚠️ 今日翻譯額度已用完，請稍後再試。"
MODEL_UNAVAILABLE_MESSAGE = "⚠️ 翻譯模型暫時無法使用。"
SERVICE_ERROR_MESSAGE = "⚠️ 翻譯服務暫時異常，請稍後再試。"
SYSTEM_ERROR_MESSAGE = "⚠️ 系統暫時異常，請稍後再試。"


def translate(text: str) -> str:
    """清理輸入、建立 Prompt、呼叫 Gemini 並處理錯誤。"""

    if not text or not text.strip():
        return EMPTY_TEXT_MESSAGE

    cleaned_text = text.strip()

    try:
        translated_text = generate_translation(
            build_translation_prompt(cleaned_text)
        )

        if not translated_text:
            logger.warning("Gemini 回傳空白翻譯結果")
            return TRANSLATION_FAILED_MESSAGE

        return translated_text

    except ClientError as error:
        error_message = str(error)

        if "429" in error_message or "RESOURCE_EXHAUSTED" in error_message:
            logger.warning("Gemini API 額度不足：%s", error)
            return QUOTA_EXCEEDED_MESSAGE

        if "404" in error_message:
            logger.error("Gemini 模型不存在或已停用：%s", error)
            return MODEL_UNAVAILABLE_MESSAGE

        logger.exception("Gemini API 錯誤")
        return SERVICE_ERROR_MESSAGE

    except Exception:
        logger.exception("翻譯時發生未知錯誤")
        return SYSTEM_ERROR_MESSAGE
