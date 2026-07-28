"""Vercel 與本機 WSGI 共用入口。"""

from app.main import app

__all__ = ["app"]
