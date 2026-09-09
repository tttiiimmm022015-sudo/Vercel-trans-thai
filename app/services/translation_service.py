import logging
import re

from google.genai.errors import ClientError

from app.prompts.translation_prompt import build_translation_prompt
from app.services.gemini_service import generate_translation


logger = logging.getLogger(__name__)

EMPTY_TEXT_MESSAGE = " Please enter text to translate."
TRANSLATION_FAILED_MESSAGE = "⚠️ Translation failed. Please try again later."
QUOTA_EXCEEDED_MESSAGE = "⚠️ Translation limit reached. Try again later."
MODEL_UNAVAILABLE_MESSAGE = "⚠️ Translation unavailable."
SERVICE_ERROR_MESSAGE = "⚠️ Translation service unavailable. Try again later."
SYSTEM_ERROR_MESSAGE = "⚠️ System error. Try again later."

THAI_PATTERN = re.compile(r"[\u0E00-\u0E7F]")
CHINESE_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")


# -----------------------------
# 超短固定詞
# -----------------------------

THAI_SHORT_TRANSLATIONS = {
    "ค่ะ": "好的",
    "คะ": "嗯？",
}


def _get_fixed_short_translation(
    text: str,
    direction: str,
) -> str | None:
    """
    處理極短、容易因缺乏上下文而翻譯不穩定的詞。

    命中固定詞時直接回傳，不呼叫 Gemini。
    """

    if direction != "TH→ZH-TW":
        return None

    normalized_text = text.strip()

    return THAI_SHORT_TRANSLATIONS.get(normalized_text)


def _normalize_for_comparison(text: str) -> str:
    """移除不影響內容的空白與常見句尾標點，用於判斷是否原樣回傳。"""

    normalized = "".join(text.split())
    return normalized.strip("。．.!！?？")


def _translation_was_not_applied(
    original: str,
    translated: str,
    direction: str,
) -> bool:
    """
    判斷模型是否把需要翻譯的中文／泰文原樣回傳。

    純數字、時間、網址等不會被誤判，因為指定方向必須同時包含
    對應來源語言的自然文字。
    """

    if direction == "TH→ZH-TW":
        contains_source_language = bool(
            THAI_PATTERN.search(original)
        )
    elif direction == "ZH-TW→TH":
        contains_source_language = bool(
            CHINESE_PATTERN.search(original)
        )
    else:
        return False

    if not contains_source_language:
        return False

    return (
        _normalize_for_comparison(original)
        == _normalize_for_comparison(translated)
    )


def _build_retry_prompt(
    text: str,
    direction: str,
) -> str:
    """第一次原樣回傳時，使用短而明確的 Prompt 重試一次。"""

    if direction == "TH→ZH-TW":
        instruction = (
            "將以下泰文翻譯成自然、道地的繁體中文。"
            "禁止回答內容，禁止解釋，禁止原樣輸出泰文。"
            "只輸出繁體中文翻譯結果。"
        )

    elif direction == "ZH-TW→TH":
        instruction = (
            "將以下繁體中文翻譯成自然、道地的泰文。"
            "禁止回答內容，禁止解釋，禁止原樣輸出中文。"
            "只輸出泰文翻譯結果。"
        )

    else:
        return build_translation_prompt(
            text=text,
            direction=direction,
        )

    return f"""你是專業翻譯員。

{instruction}

【待翻譯原文】
{text}
"""


def translate(
    text: str,
    direction: str,
) -> str:
    """清理輸入、依固定方向翻譯，並處理原樣回傳與 API 錯誤。"""

    if not text or not text.strip():
        return EMPTY_TEXT_MESSAGE

    cleaned_text = text.strip()

    # -----------------------------
    # 先檢查超短固定詞
    # -----------------------------

    fixed_translation = _get_fixed_short_translation(
        text=cleaned_text,
        direction=direction,
    )

    if fixed_translation is not None:
        logger.info(
            "使用固定短詞翻譯：%s -> %s",
            cleaned_text,
            fixed_translation,
        )
        return fixed_translation

    # -----------------------------
    # 其餘內容交給 Gemini
    # -----------------------------

    try:
        translated_text = generate_translation(
            build_translation_prompt(
                text=cleaned_text,
                direction=direction,
            )
        )

        if not translated_text:
            logger.warning(
                "Gemini 回傳空白翻譯結果"
            )
            return TRANSLATION_FAILED_MESSAGE

        same_as_input = _translation_was_not_applied(
            original=cleaned_text,
            translated=translated_text,
            direction=direction,
        )

        logger.info(
            (
                "翻譯結果檢查：direction=%s "
                "input_length=%d "
                "output_length=%d "
                "same_as_input=%s"
            ),
            direction,
            len(cleaned_text),
            len(translated_text),
            same_as_input,
        )

        if same_as_input:
            logger.warning(
                "Gemini 原樣回傳，使用固定方向短 Prompt 重試：%s",
                direction,
            )

            retry_result = generate_translation(
                _build_retry_prompt(
                    text=cleaned_text,
                    direction=direction,
                )
            )

            if not retry_result:
                logger.warning(
                    "Gemini 重試後回傳空白結果"
                )
                return TRANSLATION_FAILED_MESSAGE

            if _translation_was_not_applied(
                original=cleaned_text,
                translated=retry_result,
                direction=direction,
            ):
                logger.warning(
                    "Gemini 重試後仍原樣回傳：direction=%s",
                    direction,
                )
                return TRANSLATION_FAILED_MESSAGE

            translated_text = retry_result

        return translated_text

    except ClientError as error:
        error_message = str(error)

        if (
            "429" in error_message
            or "RESOURCE_EXHAUSTED" in error_message
        ):
            logger.warning(
                "Gemini API 額度不足：%s",
                error,
            )
            return QUOTA_EXCEEDED_MESSAGE

        if "404" in error_message:
            logger.error(
                "Gemini 模型不存在或已停用：%s",
                error,
            )
            return MODEL_UNAVAILABLE_MESSAGE

        logger.exception(
            "Gemini API 錯誤"
        )
        return SERVICE_ERROR_MESSAGE

    except Exception:
        logger.exception(
            "翻譯時發生未知錯誤"
        )
        return SYSTEM_ERROR_MESSAGE
