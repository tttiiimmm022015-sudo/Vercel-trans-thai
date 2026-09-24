import os
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("GEMINI_API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")

from app.core.config import Settings
from app.services import google_translate_service, translation_service


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "gemini_api_keys": ("key-1",),
        "line_channel_secret": "line-secret",
        "line_channel_access_token": "line-token",
        "google_translate_enabled": True,
        "google_translate_web_app_url": (
            "https://script.google.com/macros/s/test/exec"
        ),
        "google_translate_secret": "translate-secret",
        "google_translate_timeout_seconds": 8.0,
    }
    values.update(overrides)
    return Settings(**values)


class GoogleTranslateServiceTests(unittest.TestCase):
    def test_posts_to_apps_script_and_returns_translation(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "ok": True,
            "translatedText": "客人回來接我了",
        }

        with patch.object(
            google_translate_service.httpx,
            "post",
            return_value=response,
        ) as post:
            result = google_translate_service.translate_with_google(
                "ลูกค้ากลับมารับฉัน",
                "TH→ZH-TW",
                settings=_settings(),
            )

        self.assertEqual(result, "客人回來接我了")
        self.assertTrue(post.call_args.kwargs["follow_redirects"])
        self.assertEqual(post.call_args.kwargs["timeout"], 8.0)
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "secret": "translate-secret",
                "text": "ลูกค้ากลับมารับฉัน",
                "source": "th",
                "target": "zh-TW",
            },
        )

    def test_english_direction_keeps_expected_dual_format(self) -> None:
        with patch.object(
            google_translate_service,
            "_request_translation",
            side_effect=["今天工作。", "วันนี้ทำงาน"],
        ) as request_translation:
            result = google_translate_service.translate_with_google(
                "Work today.",
                "EN→ZH-TW+TH",
                settings=_settings(),
            )

        self.assertEqual(
            result,
            "中文：\n今天工作。\n\n泰文：\nวันนี้ทำงาน",
        )
        self.assertEqual(request_translation.call_count, 2)

    def test_disabled_fallback_does_not_send_request(self) -> None:
        with (
            patch.object(
                google_translate_service.httpx,
                "post",
            ) as post,
            self.assertRaises(
                google_translate_service.GoogleTranslateNotConfiguredError
            ),
        ):
            google_translate_service.translate_with_google(
                "測試",
                "ZH-TW→TH",
                settings=_settings(google_translate_enabled=False),
            )

        post.assert_not_called()


class TranslationServiceFallbackTests(unittest.TestCase):
    def test_gemini_timeout_uses_google_fallback(self) -> None:
        with (
            patch.object(
                translation_service,
                "generate_translation",
                side_effect=(
                    translation_service.GeminiRequestTimeoutError("timeout")
                ),
            ),
            patch.object(
                translation_service,
                "translate_with_google",
                return_value="客人回來接我了",
            ) as google_fallback,
        ):
            result = translation_service.translate(
                "ลูกค้ากลับมารับฉัน",
                "TH→ZH-TW",
            )

        self.assertEqual(result, "客人回來接我了")
        google_fallback.assert_called_once_with(
            text="ลูกค้ากลับมารับฉัน",
            direction="TH→ZH-TW",
        )

    def test_google_failure_keeps_existing_error_message(self) -> None:
        with (
            patch.object(
                translation_service,
                "generate_translation",
                side_effect=(
                    translation_service.GeminiRequestTimeoutError("timeout")
                ),
            ),
            patch.object(
                translation_service,
                "translate_with_google",
                side_effect=(
                    google_translate_service.GoogleTranslateError("failed")
                ),
            ),
        ):
            result = translation_service.translate(
                "ลูกค้ากลับมารับฉัน",
                "TH→ZH-TW",
            )

        self.assertEqual(
            result,
            translation_service.SERVICE_ERROR_MESSAGE,
        )

    def test_same_as_input_uses_google_after_gemini_retry(self) -> None:
        original = "客人延長時間"

        with (
            patch.object(
                translation_service,
                "generate_translation",
                side_effect=[original, original],
            ),
            patch.object(
                translation_service,
                "translate_with_google",
                return_value="ลูกค้าขยายเวลา",
            ),
        ):
            result = translation_service.translate(
                original,
                "ZH-TW→TH",
            )

        self.assertEqual(result, "ลูกค้าขยายเวลา")


if __name__ == "__main__":
    unittest.main()
