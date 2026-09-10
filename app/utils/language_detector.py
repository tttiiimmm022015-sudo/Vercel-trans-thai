import re


THAI_PATTERN = re.compile(r"[\u0E00-\u0E7F]")
CHINESE_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
ENGLISH_PATTERN = re.compile(r"[A-Za-z]")
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def _remove_non_language_content(text: str) -> str:
    """移除不應影響主要語言判斷的網址與 Email。"""

    without_urls = URL_PATTERN.sub(" ", text)
    return EMAIL_PATTERN.sub(" ", without_urls)


def detect_translation_direction(text: str) -> str:
    """判斷 LINE 訊息顯示的翻譯方向名稱。"""

    natural_text = _remove_non_language_content(text)
    thai_count = len(THAI_PATTERN.findall(natural_text))
    chinese_count = len(CHINESE_PATTERN.findall(natural_text))
    english_count = len(ENGLISH_PATTERN.findall(natural_text))

    if thai_count > max(chinese_count, english_count) and thai_count > 0:
        return "TH→ZH-TW"

    if chinese_count > max(thai_count, english_count) and chinese_count > 0:
        return "ZH-TW→TH"

    if english_count > max(chinese_count, thai_count) and english_count > 0:
        return "EN→ZH-TW+TH"

    if chinese_count > 0:
        return "ZH-TW→TH"

    if thai_count > 0:
        return "TH→ZH-TW"

    if english_count > 0:
        return "EN→ZH-TW+TH"

    return "Translator"
