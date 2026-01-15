# -*- coding: utf-8 -*-
"""
Middleware Package - 공통 미들웨어
"""

from src.application.common.middleware.access_logging import AccessLoggingMiddleware

__all__ = ["AccessLoggingMiddleware"]
