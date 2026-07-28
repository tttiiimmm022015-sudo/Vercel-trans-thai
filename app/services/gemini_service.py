import logging
import time
from functools import lru_cache

from google import genai

from app.core.config import get_settings


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    """延遲建立並快取 Gemini 用戶端，供暖實例重複使用。"""

    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def generate_translation(prompt: str) -> str:
    """將完整 Prompt 傳給 Gemini，回傳模型文字結果。"""

    settings = get_settings()
    client = get_gemini_client()
    started_at = time.perf_counter()

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config={
            "temperature": 0,
            "max_output_tokens": settings.max_output_tokens,
        },
    )

    elapsed = time.perf_counter() - started_at
    logger.info(
        "Gemini 回應完成：model=%s elapsed=%.2fs",
        settings.gemini_model,
        elapsed,
    )

    return (response.text or "").strip()
