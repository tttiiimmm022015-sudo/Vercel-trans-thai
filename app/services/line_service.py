from functools import lru_cache

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    Sender,
    TextMessage,
)

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_line_configuration() -> Configuration:
    """建立並快取 LINE Messaging API 設定。"""

    settings = get_settings()
    return Configuration(
        access_token=settings.line_channel_access_token
    )


def _build_custom_sender(
    direction: str,
    sender_icon_url: str | None,
) -> Sender | None:
    """使用翻譯方向作為名稱，並套用原發話者頭像。"""

    if not sender_icon_url:
        return None

    return Sender(
        name=(direction or "Translator").strip()[:20],
        icon_url=sender_icon_url,
    )


def reply_text(
    reply_token: str,
    text: str,
    sender_name: str | None = None,
    sender_icon_url: str | None = None,
    direction: str = "Translator",
    user_id: str | None = None,
    can_mention: bool = False,
) -> None:
    """回覆只有翻譯內容的 LINE 訊息，不加入名稱或 @ 標記。"""

    # 舊版 webhook 仍會傳入這些參數；保留參數以避免部署錯誤。
    _ = sender_name, user_id, can_mention

    translated_text = (text or "").strip()
    custom_sender = _build_custom_sender(
        direction=direction,
        sender_icon_url=sender_icon_url,
    )

    with ApiClient(get_line_configuration()) as api_client:
        messaging_api = MessagingApi(api_client)
        message = TextMessage(
            text=translated_text,
            sender=custom_sender,
        )

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[message],
            )
        )
