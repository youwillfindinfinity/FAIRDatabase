"""Session-backed handlers for the example plugin.

Subclass ``kernel.handlers.BaseHandler`` for any multi-step / session-driven
workflow (the pattern core uses for the upload → generalize → anonymize flow).
A plain JSON API plugin may not need this file at all — delete it if so.

All session keys a plugin writes MUST be namespaced ``"<plugin>:..."``
(guide §3).
"""
from kernel.handlers import BaseHandler


class ExampleHandler(BaseHandler):
    """Minimal example: stash and read a plugin-scoped session value."""

    SESSION_KEY = "example:last_label"

    def remember_label(self, label):
        self._update_session({self.SESSION_KEY: label})
        self._update_context({"last_label": label})

    def last_label(self):
        return self._session.get(self.SESSION_KEY)
