"""Session-backed workflow base class. See ``docs/PLUGIN_GUIDE.md`` §2.

Subclass ``kernel.handlers.BaseHandler`` for a handler that loads/saves a
session DataFrame and maintains a ``_ctx`` dict for templates.
"""
from src.form_handler import BaseHandler

__all__ = ["BaseHandler"]
