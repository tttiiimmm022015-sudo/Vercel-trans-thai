import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("GEMINI_API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")

from app.api import line_webhook
from app.api.line_webhook import (
    get_conversation_id,
    get_text_for_language_detection,
    is_language_menu_command,
)
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

    def test_vietnamese_direction(self) -> None:
        self.assertEqual(
            detect_translation_direction(
                "Khách muốn gia hạn thời gian đến 1:00"
            ),
            "VI→ZH-TW",
        )

    def test_unaccented_vietnamese_direction(self) -> None:
        self.assertEqual(
            detect_translation_direction("khach ve roi"),
            "VI→ZH-TW",
        )

    def test_vietnamese_mode_translates_chinese_to_vietnamese(self) -> None:
        self.assertEqual(
            detect_translation_direction(
                "客人延長到 1:00",
                target_mode="vi",
            ),
            "ZH-TW→VI",
        )

    def test_vietnamese_mode_translates_english_to_two_languages(
        self,
    ) -> None:
        self.assertEqual(
            detect_translation_direction(
                "The customer extended until 1:00.",
                target_mode="vi",
            ),
            "EN→ZH-TW+VI",
        )

    def test_english_mode_translates_thai_to_chinese_and_english(
        self,
    ) -> None:
        self.assertEqual(
            detect_translation_direction(
                "ลูกค้าต่อเวลาถึง 1:00",
                target_mode="en",
            ),
            "TH→ZH-TW+EN",
        )

    def test_english_mode_translates_chinese_to_english(self) -> None:
        self.assertEqual(
            detect_translation_direction(
                "客人延長到 1:00",
                target_mode="en",
            ),
            "ZH-TW→EN",
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


class ConversationSettingsTests(unittest.TestCase):
    def test_group_conversation_id(self) -> None:
        source = SimpleNamespace(type="group", group_id="group-123")
        self.assertEqual(
            get_conversation_id(source),
            "group:group-123",
        )

    def test_language_menu_commands_are_multilingual(self) -> None:
        self.assertTrue(is_language_menu_command("語言設定"))
        self.assertTrue(is_language_menu_command("ตั้งค่าภาษา"))
        self.assertTrue(is_language_menu_command("Chọn ngôn ngữ"))
        self.assertTrue(is_language_menu_command("Language Settings"))
        self.assertFalse(is_language_menu_command("今天工作結束"))

    def test_language_command_opens_menu_without_translation(self) -> None:
        event = SimpleNamespace(
            reply_token="reply-token",
            source=SimpleNamespace(
                type="group",
                group_id="group-123",
                user_id="user-123",
            ),
            message=SimpleNamespace(
                text="語言設定",
                mention=None,
            ),
        )

        with (
            patch.object(line_webhook, "reply_language_menu") as menu,
            patch.object(line_webhook, "translate") as translate,
        ):
            line_webhook.handle_text_message(event)

        menu.assert_called_once_with("reply-token")
        translate.assert_not_called()

    def test_vietnamese_group_mode_controls_translation_direction(
        self,
    ) -> None:
        event = SimpleNamespace(
            reply_token="reply-token",
            source=SimpleNamespace(
                type="group",
                group_id="group-123",
                user_id="user-123",
                room_id=None,
            ),
            message=SimpleNamespace(
                text="客人延長到 1:00",
                mention=None,
            ),
        )

        with (
            patch.object(
                line_webhook,
                "get_language_mode",
                return_value="vi",
            ),
            patch.object(
                line_webhook,
                "get_sender_profile",
                return_value=("Tester", None),
            ),
            patch.object(
                line_webhook,
                "translate",
                return_value="Khách gia hạn đến 1:00.",
            ) as translate,
            patch.object(line_webhook, "reply_text"),
        ):
            line_webhook.handle_text_message(event)

        translate.assert_called_once_with(
            text="客人延長到 1:00",
            direction="ZH-TW→VI",
        )

    def test_new_group_join_opens_language_menu(self) -> None:
        event = SimpleNamespace(
            reply_token="join-token",
            source=SimpleNamespace(type="group"),
        )

        with patch.object(
            line_webhook,
            "reply_language_menu",
        ) as menu:
            line_webhook.handle_join_event(event)

        menu.assert_called_once_with("join-token")

    def test_any_member_can_switch_group_language(self) -> None:
        event = SimpleNamespace(
            reply_token="postback-token",
            source=SimpleNamespace(
                type="group",
                group_id="group-123",
            ),
            postback=SimpleNamespace(
                data="action=set_language&language=en",
            ),
        )

        with (
            patch.object(
                line_webhook,
                "set_language_mode",
                return_value=True,
            ) as set_mode,
            patch.object(
                line_webhook,
                "reply_language_confirmation",
            ) as confirm,
        ):
            line_webhook.handle_postback_event(event)

        set_mode.assert_called_once_with(
            conversation_id="group:group-123",
            mode="en",
        )
        confirm.assert_called_once_with(
            reply_token="postback-token",
            mode="en",
            persisted=True,
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

    def test_vietnamese_prompts_have_fixed_directions(self) -> None:
        vi_to_zh = build_translation_prompt(
            "Khách về rồi",
            "VI→ZH-TW",
        )
        zh_to_vi = build_translation_prompt(
            "客人回去了",
            "ZH-TW→VI",
        )

        self.assertIn("只輸出中文譯文", vi_to_zh)
        self.assertIn("只輸出越南文譯文", zh_to_vi)

    def test_multilingual_mode_prompts_have_fixed_output_formats(
        self,
    ) -> None:
        en_to_vi = build_translation_prompt(
            "Customer left.",
            "EN→ZH-TW+VI",
        )
        th_to_en = build_translation_prompt(
            "ลูกค้ากลับแล้ว",
            "TH→ZH-TW+EN",
        )

        self.assertIn("越南文：", en_to_vi)
        self.assertIn("英文：", th_to_en)


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


class SettingsTests(unittest.TestCase):
    def test_marketplace_prefixed_upstash_variables_are_supported(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "UPSTASH_REDIS_REST_URL": "",
                "UPSTASH_REDIS_REST_TOKEN": "",
                "UPSTASH_REDIS_REST_KV_REST_API_URL": (
                    "https://example.upstash.io"
                ),
                "UPSTASH_REDIS_REST_KV_REST_API_TOKEN": "token",
            },
            clear=False,
        ):
            settings = Settings.from_env()

        self.assertEqual(
            settings.upstash_redis_rest_url,
            "https://example.upstash.io",
        )
        self.assertEqual(settings.upstash_redis_rest_token, "token")


if __name__ == "__main__":
    unittest.main()
