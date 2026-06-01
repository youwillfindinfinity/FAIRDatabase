"""Pytest fixtures for the horizontal FL plugin test suite.

The plugin tests live outside the project ``tests/`` tree, so that conftest is
not a parent and its shared app/client/auth fixtures must be imported
explicitly.
"""
from tests.conftest import *  # noqa: F401,F403 — shared app/client/auth fixtures
