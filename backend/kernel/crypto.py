"""Secure-aggregation crypto for FL plugins. See ``docs/PLUGIN_GUIDE.md`` §2.

AES-256-GCM weight encryption. A plugin calls ``decrypt_weights(payload,
task_id)`` and the secret is resolved internally from the app config — the
plugin never handles ``SECRET_KEY``.
"""
from kernel.crypto_impl import decrypt_weights, encrypt_weights

__all__ = ["encrypt_weights", "decrypt_weights"]
