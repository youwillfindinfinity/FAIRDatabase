"""Demo API package.

The Blueprint lives in ``src.demo.routes`` (imported directly by app.py).
This module intentionally defines no Blueprint — a second one here shadowed
the real one and caused a duplicate-name registration ambiguity.
"""
