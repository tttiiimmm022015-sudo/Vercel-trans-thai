import logging

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.core.config import get_settings
from app.services.line_service import reply_text
from app.services.translation_service import translate
from app.utils.language_detector import detect_translation_direction


logger = logging.getLogger(__name__)
settings = get_settings()

handler = WebhookHandler(settings.line_channel_secret)
line_configuration = Configuration(
    access_token=settings.line_channel_access_token
)


def get_sender_name(event: MessageEvent) -> str:
    """
    取得一對一聊天的 LINE 顯示名稱。

    群組和多人聊天室使用真正的 LINE mention，不必先呼叫 Profile API，
    可少一次外部網路請求並降低整體延遲。
    """

    user_id = getattr(event.source, "user_id", None)
    if not user_id:
        return "未知使用者"

    try:
        with ApiClient(line_configuration) as api_client:
            profile = MessagingApi(api_client).get_profile(user_id=user_id)

        return getattr(profile, "display_name", None) or "未知使用者"

    except Exception:
        logger.exception("取得 LINE 發送者名稱失敗：user_id=%s", user_id)
        return "未知使用者"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent) -> None:
    """處理 LINE 文字訊息並回覆翻譯結果。"""

    user_text = (getattr(event.message, "text", "") or "").strip()
    if not user_text:
        return

    try:
        source_type = getattr(event.source, "type", "")
        user_id = getattr(event.source, "user_id", None)
        group_id = getattr(event.source, "group_id", None)
        room_id = getattr(event.source, "room_id", None)

        can_mention = source_type in ("group", "room") and bool(user_id)

        # 群組／多人聊天室不需要 Profile API；一對一才取得顯示名稱。
        sender_name = (
            "LINE 使用者"
            if can_mention
            else get_sender_name(event)
        )

        direction = detect_translation_direction(user_text)

        logger.info(
            (
                "收到訊息：source_type=%s user_id=%s group_id=%s "
                "room_id=%s direction=%s can_mention=%s"
            ),
            source_type,
            user_id,
            group_id,
            room_id,
            direction,
            can_mention,
        )

        translated_text = translate(user_text)

        reply_text(
            reply_token=event.reply_token,
            text=translated_text,
            sender_name=sender_name,
            user_id=user_id,
            can_mention=can_mention,
        )

    except Exception:
        logger.exception("處理 LINE 訊息失敗")
