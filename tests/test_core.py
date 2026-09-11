import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("GEMINI_API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")

from app.api.line_webhook import get_text_for_language_detection
from app.core.config import Settings
from app.prompts.translation_prompt import build_translation_prompt
from app.services import gemini_service
from app.utils.language_detector import detect_translation_direction


class LanguageDetectorTests(unittest.TestCase):
    def test_thai_with_url_is_thai(self) -> None:
        result = detect_translation_direction(
            "https://example.com วันนี้ทำงาน"
        )
        self.assertEqual(result, "TH→ZH-TW")

    def test_chinese_with_email_is_chinese(self) -> None:
        result = detect_translation_direction(
            "test@example.com 今天上班"
        )
        self.assertEqual(result, "ZH-TW→TH")

    def test_english_direction(self) -> None:
        self.assertEqual(
            detect_translation_direction("Work finished?"),
            "EN→ZH-TW+TH",
        )

    def test_line_mention_is_removed_before_detection(self) -> None:
        text = "@Wu Chen วันนี้ทำงาน"
        mentionee = SimpleNamespace(index=0, length=8)
        message = SimpleNamespace(
            mention=SimpleNamespace(mentionees=[mentionee])
        )
        detection_text = get_text_for_language_detection(message, text)
        self.assertEqual(
            detect_translation_direction(detection_text),
            "TH→ZH-TW",
        )


class PromptTests(unittest.TestCase):
    def test_prompt_is_compact_and_contains_original_text(self) -> None:
        original = "ลูกค้าฉันกลับแล้ว"
        prompt = build_translation_prompt(original, "TH→ZH-TW")

        self.assertIn(original, prompt)
        self.assertIn("只輸出中文譯文", prompt)
        self.assertIn("不得誤翻成「孩子」", prompt)
        self.assertIn("ลงเวลา", prompt)
        self.assertLess(len(prompt), 4000)


class GeminiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        gemini_service._key_cooldowns.clear()

    def test_available_keys_keep_configured_order(self) -> None:
        indexes = gemini_service._get_available_key_indexes(
            5,
            "model",
        )
        self.assertEqual(indexes, [0, 1, 2, 3, 4])

    def test_cooldown_key_is_skipped(self) -> None:
        gemini_service._mark_key_cooldown(
            "model",
            2,
            60,
        )
        indexes = gemini_service._get_available_key_indexes(
            5,
            "model",
        )
        self.assertEqual(indexes, [0, 1, 3, 4])

    def test_empty_primary_uses_fallback(self) -> None:
        settings = Settings(
            gemini_api_keys=("key-1", "key-2"),
            line_channel_secret="secret",
            line_channel_access_token="token",
            gemini_model="primary-model",
            gemini_fallback_model="fallback-model",
        )

        with (
            patch.object(
                gemini_service,
                "get_settings",
                return_value=settings,
            ),
            patch.object(
                gemini_service,
                "_generate_with_model",
                side_effect=[
                    gemini_service.EmptyGeminiResponseError(
                        "empty"
                    ),
                    "翻譯成功",
                ],
            ) as generate,
        ):
            result = gemini_service.generate_translation(
                "prompt"
            )

        self.assertEqual(result, "翻譯成功")
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(
            generate.call_args_list[1].kwargs["model"],
            "fallback-model",
        )

    def test_same_primary_and_fallback_is_not_called_twice(
        self,
    ) -> None:
        settings = Settings(
            gemini_api_keys=("key-1", "key-2"),
            line_channel_secret="secret",
            line_channel_access_token="token",
            gemini_model="same-model",
            gemini_fallback_model="same-model",
        )

        with (
            patch.object(
                gemini_service,
                "get_settings",
                return_value=settings,
            ),
            patch.object(
                gemini_service,
                "_generate_with_model",
                side_effect=(
                    gemini_service.EmptyGeminiResponseError(
                        "empty"
                    )
                ),
            ) as generate,
        ):
            with self.assertRaises(
                gemini_service.EmptyGeminiResponseError
            ):
                gemini_service.generate_translation(
                    "prompt"
                )

        self.assertEqual(generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
