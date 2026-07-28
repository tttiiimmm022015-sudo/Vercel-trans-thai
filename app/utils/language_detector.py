import re


THAI_PATTERN = re.compile(r"[\u0E00-\u0E7F]")
CHINESE_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
ENGLISH_PATTERN = re.compile(r"[A-Za-z]")


def detect_translation_direction(text: str) -> str:
    """判斷 LINE 訊息顯示的翻譯方向名稱。"""

    thai_count = len(THAI_PATTERN.findall(text))
    chinese_count = len(CHINESE_PATTERN.findall(text))
    english_count = len(ENGLISH_PATTERN.findall(text))

    if thai_count > max(chinese_count, english_count) and thai_count > 0:
        return "TH→ZH-TW"

    if chinese_count > max(thai_count, english_count) and chinese_count > 0:
        return "ZH-TW→TH"

    if english_count > max(chinese_count, thai_count) and english_count > 0:
        return "EN→TH"

    if chinese_count > 0:
        return "ZH-TW→TH"

    if thai_count > 0:
        return "TH→ZH-TW"

    if english_count > 0:
        return "EN→TH"

    return "Translator"