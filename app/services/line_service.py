from functools import lru_cache

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MentionSubstitutionObject,
    MessagingApi,
    ReplyMessageRequest,
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


def reply_text(
    reply_token: str,
    text: str,
    sender_name: str,
    user_id: str | None = None,
    can_mention: bool = False,
) -> None:
    """
    回覆 LINE 翻譯訊息。

    群組／多人聊天室：
    真正標記原訊息發送者。

    一對一聊天室：
    顯示普通使用者名稱。
    """

    display_name = (sender_name or "未知使用者").strip()
    translated_text = (text or "").strip()

    with ApiClient(get_line_configuration()) as api_client:
        messaging_api = MessagingApi(api_client)

        if can_mention and user_id:
            # Text Message v2 的 {user} 會被替換成真正的 LINE 標記
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
            )

        else:
            # 一對一聊天不能使用群組標記，改為普通文字名稱
            message = TextMessage(
                text=(
                    f"{display_name}:\n "
                    f"{translated_text}"
                )
            )

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[message],
            )
        )