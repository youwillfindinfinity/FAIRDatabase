"""Authentication / role gate. See ``docs/PLUGIN_GUIDE.md`` §2.

    @kernel.auth.login_required()                   # any authenticated user
    @kernel.auth.login_required("admin", "curator") # only listed roles -> else 403

Sets ``g.user`` (uuid) and ``g.role`` (str) for the request.
"""
from src.auth.decorators import DEFAULT_ROLE, login_required

__all__ = ["login_required", "DEFAULT_ROLE"]
