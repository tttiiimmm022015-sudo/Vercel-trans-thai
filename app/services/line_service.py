from functools import lru_cache

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    Sender,
    TextMessage,
)

from app.core.config import get_settings


LANGUAGE_MENU_TEXT = """🌐 請選擇這個群組的翻譯語言
กรุณาเลือกภาษาแปลสำหรับกลุ่มนี้
Vui lòng chọn ngôn ngữ dịch cho nhóm này
Please select a translation language for this group.

中文會固定保留；所有群組成員都可以切換語言。
ทุกคนในกลุ่มสามารถเปลี่ยนภาษาได้
Mọi thành viên trong nhóm đều có thể đổi ngôn ngữ.
Anyone in the group can change the language later by typing “language”."""

LANGUAGE_CONFIRMATIONS = {
    "th": (
        "✅ 已切換為中文 ↔ 泰文\n"
        "ตั้งค่าเป็นภาษาจีน ↔ ภาษาไทยแล้ว"
    ),
    "vi": (
        "✅ 已切換為中文 ↔ 越南文\n"
        "Đã chuyển sang chế độ tiếng Trung ↔ tiếng Việt."
    ),
    "en": (
        "✅ 已切換為中文 ↔ 英文\n"
        "Switched to Chinese ↔ English mode."
    ),
}

LANGUAGE_BUTTONS = (
    ("🇹🇭 ไทย", "th"),
    ("🇻🇳 Tiếng Việt", "vi"),
    ("🇬🇧 English", "en"),
)


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


def reply_language_menu(reply_token: str) -> None:
    """顯示所有國籍使用者都能理解的群組語言選單。"""

    quick_reply = QuickReply(
        items=[
            QuickReplyItem(
                action=PostbackAction(
                    label=label,
                    data=f"action=set_language&language={mode}",
                    display_text=label,
                )
            )
            for label, mode in LANGUAGE_BUTTONS
        ]
    )
    message = TextMessage(
        text=LANGUAGE_MENU_TEXT,
        quick_reply=quick_reply,
    )

    with ApiClient(get_line_configuration()) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[message],
            )
        )


def reply_language_confirmation(
    reply_token: str,
    mode: str,
    persisted: bool,
) -> None:
    """回覆群組語言切換結果。"""

    text = LANGUAGE_CONFIRMATIONS[mode]
    if not persisted:
        text += (
            "\n\n⚠️ 已暫時切換，但永久儲存尚未設定；"
            "Vercel 重新啟動後會恢復泰文模式。"
        )

    with ApiClient(get_line_configuration()) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
