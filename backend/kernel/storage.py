"""Supabase Storage wrapper for plugin blobs. See ``docs/PLUGIN_GUIDE.md`` §2, §3.

Plugins never touch ``supabase_extension.client`` directly. ``upload_stream``,
``signed_url`` and ``delete_object`` enforce two boundaries:

  1. **Bucket ownership.** Inside a plugin request, the bucket must start with
     the calling plugin's ``"<name>-"`` prefix (set by the loader's
     ``before_request`` hook via ``kernel.context.current_plugin``). A plugin
     cannot read or mutate another plugin's bucket.
  2. **MIME whitelist.** ``upload_stream`` rejects ``content_type`` not in the
     bucket's manifest-declared ``mime_whitelist``. An empty / missing
     whitelist disables the check (back-compat for buckets created before the
     field existed).

A ``storage_path`` is the canonical ``"<bucket>/<object key>"`` string a plugin
stores in its own catalog row.

Core code (non-plugin, no ``current_plugin``) bypasses the ownership check —
this lets the admin console and tests use the helper without ceremony.
"""
from config import supabase_extension
from kernel.context import current_plugin

__all__ = [
    "upload_stream",
    "signed_url",
    "delete_object",
    "split_path",
    "register_bucket",
]

DEFAULT_SIGNED_URL_TTL = 600  # seconds (10 min)

# Populated by ``kernel.loader.register_plugins`` at boot: bucket_id → {
#   "plugin": <plugin name>, "mime_whitelist": frozenset[str] | None, ...
# }. Used to enforce the MIME whitelist and the plugin-owns-bucket rule.
_BUCKET_REGISTRY = {}


def register_bucket(plugin_name, bucket_spec):
    """Record a manifest-declared bucket so upload/access checks can find it.

    Called by the loader once per plugin bucket at boot. Safe to call twice
    (later wins) — that lets tests reset state by re-registering.
    """
    bid = bucket_spec.get("id")
    if not bid:
        return
    whitelist = bucket_spec.get("mime_whitelist")
    _BUCKET_REGISTRY[bid] = {
        "plugin": plugin_name,
        "mime_whitelist": frozenset(whitelist) if whitelist else None,
    }


def split_path(storage_path):
    """Split a ``"<bucket>/<key>"`` storage path into ``(bucket, key)``."""
    bucket, _, key = storage_path.partition("/")
    return bucket, key


def _assert_plugin_owns(bucket):
    """If we're inside a plugin request, the bucket must belong to that plugin.

    Outside a request (boot-time helpers, tests, core admin console) the check
    is skipped — only plugin code is sandboxed.
    """
    caller = current_plugin()
    if caller is None:
        return
    if not bucket.startswith(f"{caller}-"):
        raise PermissionError(
            f"plugin {caller!r} may not access bucket {bucket!r} "
            "(PLUGIN_GUIDE.md §3)"
        )


def upload_stream(bucket, key, fileobj, content_type, *, upsert=False):
    """Upload an open binary file object to ``bucket`` under ``key``.

    Enforces plugin-owns-bucket and the bucket's declared ``mime_whitelist``.
    Returns the canonical ``storage_path`` (``"<bucket>/<key>"``). Raises on
    failure — the caller translates that into an HTTP error.
    """
    _assert_plugin_owns(bucket)
    spec = _BUCKET_REGISTRY.get(bucket)
    if spec and spec["mime_whitelist"] and content_type not in spec["mime_whitelist"]:
        raise PermissionError(
            f"content_type {content_type!r} not in mime_whitelist for "
            f"bucket {bucket!r} (PLUGIN_GUIDE.md §5)"
        )
    supabase_extension.client.storage.from_(bucket).upload(
        key,
        fileobj,
        file_options={
            "content-type": content_type,
            "upsert": "true" if upsert else "false",
        },
    )
    return f"{bucket}/{key}"


def signed_url(storage_path, ttl=DEFAULT_SIGNED_URL_TTL):
    """Return a short-lived signed URL for ``storage_path``, or ``None`` on failure."""
    try:
        bucket, key = split_path(storage_path)
        if not bucket or not key:
            return None
        _assert_plugin_owns(bucket)
        resp = supabase_extension.client.storage.from_(bucket).create_signed_url(
            key, ttl,
        )
        return resp.get("signedURL") or resp.get("signed_url")
    except PermissionError:
        raise
    except Exception:
        return None


def delete_object(storage_path):
    """Delete the blob at ``storage_path``. Best-effort; returns True on success."""
    try:
        bucket, key = split_path(storage_path)
        if not bucket or not key:
            return False
        _assert_plugin_owns(bucket)
        supabase_extension.client.storage.from_(bucket).remove([key])
        return True
    except PermissionError:
        raise
    except Exception:
        return False
