import logging
import re
from urllib.parse import parse_qs

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
)
from linebot.v3.webhooks import (
    JoinEvent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

from app.core.config import get_settings
from app.services.language_mode_service import (
    LanguageModeStoreError,
    get_language_mode,
    set_language_mode,
)
from app.services.line_service import (
    reply_language_confirmation,
    reply_language_menu,
    reply_text,
)
from app.services.translation_service import translate
from app.utils.language_detector import detect_translation_direction


logger = logging.getLogger(__name__)
settings = get_settings()

handler = WebhookHandler(settings.line_channel_secret)
line_configuration = Configuration(
    access_token=settings.line_channel_access_token
)

LANGUAGE_MENU_COMMANDS = frozenset(
    {
        "語言設定",
        "语言设置",
        "選擇語言",
        "选择语言",
        "ภาษา",
        "ตั้งค่าภาษา",
        "เลือกภาษา",
        "cài đặt ngôn ngữ",
        "chọn ngôn ngữ",
        "language",
        "language settings",
    }
)


def get_conversation_id(source: object) -> str | None:
    """取得群組、多人聊天室或一對一聊天的穩定識別碼。"""

    source_type = getattr(source, "type", "")
    id_attributes = {
        "group": "group_id",
        "room": "room_id",
        "user": "user_id",
    }
    attribute = id_attributes.get(source_type)
    if attribute is None:
        return None

    source_id = getattr(source, attribute, None)
    if not source_id:
        return None
    return f"{source_type}:{source_id}"


def is_language_menu_command(text: str) -> bool:
    normalized = " ".join(text.casefold().strip().split())
    return normalized in LANGUAGE_MENU_COMMANDS


def get_text_for_language_detection(
    message: TextMessageContent,
    text: str,
) -> str:
    """移除 LINE Mention 顯示名稱，避免英文姓名影響語言判斷。"""

    mention = getattr(message, "mention", None)
    mentionees = getattr(mention, "mentionees", None) or []
    ranges: list[tuple[int, int]] = []

    for mentionee in mentionees:
        index = getattr(mentionee, "index", None)
        length = getattr(mentionee, "length", None)
        if isinstance(index, int) and isinstance(length, int) and length > 0:
            ranges.append((index, index + length))

    detection_text = text
    for start, end in sorted(ranges, reverse=True):
        if 0 <= start < end <= len(detection_text):
            detection_text = detection_text[:start] + detection_text[end:]

    return detection_text


def get_sender_profile(event: MessageEvent) -> tuple[str, str | None]:
    """依聊天類型取得原訊息發送者的名稱與頭像網址。"""

    source_type = getattr(event.source, "type", "")
    user_id = getattr(event.source, "user_id", None)
    group_id = getattr(event.source, "group_id", None)
    room_id = getattr(event.source, "room_id", None)

    if not user_id:
        return "未知使用者", None

    try:
        with ApiClient(line_configuration) as api_client:
            messaging_api = MessagingApi(api_client)

            if source_type == "group" and group_id:
                profile = messaging_api.get_group_member_profile(
                    group_id=group_id,
                    user_id=user_id,
                )
            elif source_type == "room" and room_id:
                profile = messaging_api.get_room_member_profile(
                    room_id=room_id,
                    user_id=user_id,
                )
            else:
                profile = messaging_api.get_profile(user_id=user_id)

        display_name = (
            getattr(profile, "display_name", None)
            or "未知使用者"
        )
        picture_url = getattr(profile, "picture_url", None)
        return display_name, picture_url

    except Exception:
        logger.exception(
            "取得 LINE 發送者資料失敗：source_type=%s user_id=%s",
            source_type,
            user_id,
        )
        return "未知使用者", None


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
        conversation_id = get_conversation_id(event.source)

        if is_language_menu_command(user_text):
            reply_language_menu(event.reply_token)
            return

        can_mention = source_type in ("group", "room") and bool(user_id)
        sender_name, sender_icon_url = get_sender_profile(event)
        detection_text = get_text_for_language_detection(
            message=event.message,
            text=user_text,
        )
        if not re.search(
            (
                r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF"
                r"\u0E00-\u0E7F\u3400-\u4DBF\u4E00-\u9FFF]"
            ),
            detection_text,
        ):
            logger.info("略過不含可翻譯文字的訊息")
            return
        language_mode = get_language_mode(conversation_id)
        direction = detect_translation_direction(
            detection_text,
            target_mode=language_mode,
        )

        logger.info(
            (
                "收到訊息：source_type=%s user_id=%s group_id=%s "
                "room_id=%s language_mode=%s direction=%s "
                "can_mention=%s has_avatar=%s"
            ),
            source_type,
            user_id,
            group_id,
            room_id,
            language_mode,
            direction,
            can_mention,
            bool(sender_icon_url),
        )

        translated_text = translate(
            text=user_text,
            direction=direction,
        )

        reply_text(
            reply_token=event.reply_token,
            text=translated_text,
            sender_name=sender_name,
            sender_icon_url=sender_icon_url,
            direction=direction,
            user_id=user_id,
            can_mention=can_mention,
        )

    except Exception:
        logger.exception("處理 LINE 訊息失敗")
        raise


@handler.add(JoinEvent)
def handle_join_event(event: JoinEvent) -> None:
    """新群組加入機器人時顯示多語言設定選單。"""

    logger.info(
        "機器人加入聊天室：source_type=%s",
        getattr(event.source, "type", ""),
    )
    reply_language_menu(event.reply_token)


@handler.add(PostbackEvent)
def handle_postback_event(event: PostbackEvent) -> None:
    """允許任何群組成員使用按鈕切換翻譯語言。"""

    postback_data = getattr(event.postback, "data", "") or ""
    parameters = parse_qs(postback_data, keep_blank_values=True)
    if parameters.get("action") != ["set_language"]:
        return

    selected_values = parameters.get("language", [])
    selected_mode = selected_values[0] if selected_values else ""
    conversation_id = get_conversation_id(event.source)
    if not conversation_id or selected_mode not in {"th", "vi", "en"}:
        logger.warning("收到無效的語言設定 Postback")
        return

    try:
        persisted = set_language_mode(
            conversation_id=conversation_id,
            mode=selected_mode,
        )
    except LanguageModeStoreError:
        logger.exception("語言模式永久保存失敗，保留暫存設定")
        persisted = False

    if event.reply_token:
        reply_language_confirmation(
            reply_token=event.reply_token,
            mode=selected_mode,
            persisted=persisted,
        )
