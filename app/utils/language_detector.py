import re


THAI_PATTERN = re.compile(r"[\u0E00-\u0E7F]")
CHINESE_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
ENGLISH_PATTERN = re.compile(r"[A-Za-z]")
VIETNAMESE_MARK_PATTERN = re.compile(
    r"[\u0102\u0103\u00C2\u00E2\u0110\u0111\u00CA\u00EA"
    r"\u00D4\u00F4\u01A0\u01A1\u01AF\u01B0\u1EA0-\u1EF9]"
)
VIETNAMESE_WORD_PATTERN = re.compile(
    r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]+"
)
VIETNAMESE_COMMON_WORDS = frozenset(
    {
        "anh",
        "bao",
        "ban",
        "cho",
        "cua",
        "da",
        "dang",
        "den",
        "di",
        "duoc",
        "em",
        "gio",
        "hom",
        "khach",
        "khong",
        "lam",
        "minh",
        "muon",
        "nay",
        "nguoi",
        "phong",
        "roi",
        "se",
        "them",
        "toi",
        "ve",
        "voi",
        "xong",
    }
)
VIETNAMESE_STRONG_WORDS = frozenset(
    {"duoc", "khach", "khong", "nguoi"}
)
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def _remove_non_language_content(text: str) -> str:
    """移除不應影響主要語言判斷的網址與 Email。"""

    without_urls = URL_PATTERN.sub(" ", text)
    return EMAIL_PATTERN.sub(" ", without_urls)


def _count_latin_languages(text: str) -> tuple[int, int]:
    """分開計算越南文與英文拉丁字母，避免越南文被判成英文。"""

    vietnamese_count = 0
    english_count = 0
    words = VIETNAMESE_WORD_PATTERN.findall(text)
    lowered_words = [word.casefold() for word in words]
    common_word_hits = sum(
        word in VIETNAMESE_COMMON_WORDS for word in lowered_words
    )
    unaccented_vietnamese = common_word_hits >= 2 or (
        len(lowered_words) == 1
        and lowered_words[0] in VIETNAMESE_STRONG_WORDS
    )

    for word, lowered_word in zip(words, lowered_words):
        ascii_letter_count = len(ENGLISH_PATTERN.findall(word))
        if VIETNAMESE_MARK_PATTERN.search(word) or (
            unaccented_vietnamese
            and lowered_word in VIETNAMESE_COMMON_WORDS
        ):
            vietnamese_count += len(word)
        else:
            english_count += ascii_letter_count

    return vietnamese_count, english_count


def detect_source_language(text: str) -> str:
    """判斷訊息的主要來源語言。"""

    natural_text = _remove_non_language_content(text)
    thai_count = len(THAI_PATTERN.findall(natural_text))
    chinese_count = len(CHINESE_PATTERN.findall(natural_text))
    vietnamese_count, english_count = _count_latin_languages(natural_text)

    if (
        vietnamese_count > max(thai_count, chinese_count)
        and vietnamese_count > 0
    ):
        return "vi"

    if thai_count > max(chinese_count, english_count) and thai_count > 0:
        return "th"

    if chinese_count > max(thai_count, english_count) and chinese_count > 0:
        return "zh-TW"

    if english_count > max(chinese_count, thai_count) and english_count > 0:
        return "en"

    if vietnamese_count > 0:
        return "vi"

    if chinese_count > 0:
        return "zh-TW"

    if thai_count > 0:
        return "th"

    if english_count > 0:
        return "en"

    return "unknown"


def detect_translation_direction(
    text: str,
    target_mode: str = "th",
) -> str:
    """依來源語言與聊天室模式決定翻譯輸出。"""

    source_language = detect_source_language(text)
    direction_map = {
        "th": {
            "th": "TH→ZH-TW",
            "zh-TW": "ZH-TW→TH",
            "en": "EN→ZH-TW+TH",
            "vi": "VI→ZH-TW",
        },
        "vi": {
            "vi": "VI→ZH-TW",
            "zh-TW": "ZH-TW→VI",
            "en": "EN→ZH-TW+VI",
            "th": "TH→ZH-TW",
        },
        "en": {
            "en": "EN→ZH-TW",
            "zh-TW": "ZH-TW→EN",
            "th": "TH→ZH-TW+EN",
            "vi": "VI→ZH-TW+EN",
        },
    }
    active_map = direction_map.get(target_mode, direction_map["th"])
    return active_map.get(source_language, "Translator")
