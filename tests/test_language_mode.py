import os
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("GEMINI_API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")

from app.core.config import Settings
from app.services import language_mode_service


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "gemini_api_keys": ("key-1",),
        "line_channel_secret": "line-secret",
        "line_channel_access_token": "line-token",
    }
    values.update(overrides)
    return Settings(**values)


class LanguageModeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        language_mode_service.clear_memory_modes()

    def test_old_group_defaults_to_thai(self) -> None:
        self.assertEqual(
            language_mode_service.get_language_mode(
                "group:old-group",
                settings=_settings(),
            ),
            "th",
        )

    def test_without_redis_switch_is_temporary(self) -> None:
        persisted = language_mode_service.set_language_mode(
            "group:test",
            "vi",
            settings=_settings(),
        )

        self.assertFalse(persisted)
        self.assertEqual(
            language_mode_service.get_language_mode(
                "group:test",
                settings=_settings(),
            ),
            "vi",
        )

    def test_redis_setting_is_persisted(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result": "OK"}
        settings = _settings(
            upstash_redis_rest_url="https://example.upstash.io",
            upstash_redis_rest_token="redis-token",
        )

        with patch.object(
            language_mode_service.httpx,
            "post",
            return_value=response,
        ) as post:
            persisted = language_mode_service.set_language_mode(
                "group:test",
                "en",
                settings=settings,
            )

        self.assertTrue(persisted)
        self.assertEqual(post.call_args.kwargs["json"][0], "SET")
        self.assertNotIn("group:test", post.call_args.kwargs["json"][1])
        self.assertEqual(post.call_args.kwargs["json"][2], "en")

    def test_redis_setting_is_loaded(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result": "vi"}

        with patch.object(
            language_mode_service.httpx,
            "post",
            return_value=response,
        ):
            mode = language_mode_service.get_language_mode(
                "group:test",
                settings=_settings(
                    upstash_redis_rest_url="https://example.upstash.io",
                    upstash_redis_rest_token="redis-token",
                ),
            )

        self.assertEqual(mode, "vi")

    def test_invalid_language_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            language_mode_service.set_language_mode(
                "group:test",
                "ja",
                settings=_settings(),
            )


if __name__ == "__main__":
    unittest.main()
