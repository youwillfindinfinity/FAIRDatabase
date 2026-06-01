"""FAIRDatabase plugins package.

Each subdirectory with a ``plugin.py`` exposing a module-level ``PLUGIN`` is
auto-discovered by ``kernel.loader`` at boot. Directories whose name starts
with ``_`` (e.g. ``_template``) are skipped. See ``docs/PLUGIN_GUIDE.md``.
"""
