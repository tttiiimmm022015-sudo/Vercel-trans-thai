from functools import lru_cache

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MentionSubstitutionObject,
    MessagingApi,
    ReplyMessageRequest,
    Sender,
    TextMessage,
    TextMessageV2,
    UserMentionTarget,
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
    """建立翻譯訊息專用名稱，並套用原發話者頭像。"""

    if not sender_icon_url:
        return None

    display_direction = (direction or "Translator").strip()[:20]

    return Sender(
        name=display_direction,
        icon_url=sender_icon_url,
    )


def reply_text(
    reply_token: str,
    text: str,
    sender_name: str,
    sender_icon_url: str | None = None,
    direction: str = "Translator",
    user_id: str | None = None,
    can_mention: bool = False,
) -> None:
    """
    回覆 LINE 翻譯訊息。

    有取得頭像時，翻譯訊息會使用原發話者頭像；取得失敗時，
    自動使用 LINE 官方帳號原本的名稱與頭像。
    """

    display_name = (sender_name or "未知使用者").strip()
    translated_text = (text or "").strip()
    custom_sender = _build_custom_sender(
        direction=direction,
        sender_icon_url=sender_icon_url,
    )

    with ApiClient(get_line_configuration()) as api_client:
        messaging_api = MessagingApi(api_client)

        if can_mention and user_id:
            message = TextMessageV2(
                text=(
                    "{user} :\n "
                    f"{translated_text}"
                ),
                substitution={
                    "user": MentionSubstitutionObject(
                        mentionee=UserMentionTarget(
                            user_id=user_id,
                        )
                    )
                },
                sender=custom_sender,
            )

        else:
            message = TextMessage(
                text=(
                    f"{display_name}:\n "
                    f"{translated_text}"
                ),
                sender=custom_sender,
            )

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[message],
            )
        )
