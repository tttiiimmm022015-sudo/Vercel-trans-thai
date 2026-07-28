import logging
import time

from flask import Flask, abort, request
from linebot.v3.exceptions import InvalidSignatureError

from app.api.line_webhook import handler
from app.core.config import get_settings
from app.utils.logger import configure_logging


logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """建立 Flask 應用程式。"""

    settings = get_settings()
    configure_logging(settings.log_level)

    flask_app = Flask(__name__)

    @flask_app.get("/")
    def home() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "LINE Translator Bot",
            "platform": "Vercel",
        }

    @flask_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @flask_app.post("/callback")
    def callback() -> str:
        started_at = time.perf_counter()
        signature = request.headers.get("X-Line-Signature", "")
        body = request.get_data(as_text=True)

        if not signature:
            abort(400, description="Missing X-Line-Signature")

        try:
            handler.handle(body, signature)
        except InvalidSignatureError:
            logger.warning("LINE Webhook 簽章驗證失敗")
            abort(400, description="Invalid signature")
        except Exception:
            logger.exception("LINE Webhook 處理失敗")
            abort(500)

        logger.info(
            "LINE Webhook 完成：elapsed=%.2fs",
            time.perf_counter() - started_at,
        )
        return "OK"

    return flask_app


app = create_app()
