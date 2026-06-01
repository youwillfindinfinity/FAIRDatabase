"""User-facing error type. See ``docs/PLUGIN_GUIDE.md`` §2.

    raise kernel.errors.GenericExceptionHandler("msg", status_code=400)
"""
from src.exceptions import GenericExceptionHandler

__all__ = ["GenericExceptionHandler"]
