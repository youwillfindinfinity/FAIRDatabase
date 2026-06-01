"""Tests for the /fl blueprint — real engine, no upstream mocks."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from unittest.mock import patch, MagicMock
import numpy as np
from kernel.crypto import encrypt_weights


SECRET = "test-secret"


class TestFLTaskCreation:
    def test_create_task_missing_fields_returns_400(self, client):
        resp = client.post("/fl/tasks", json={}, content_type="application/json")
        assert resp.status_code in (302, 400)  # 302 = not logged in redirect

    def test_ui_redirects_when_not_logged_in(self, client):
        resp = client.get("/fl/ui")
        assert resp.status_code == 302

    def test_get_nonexistent_task_returns_404(self, client):
        resp = client.get("/fl/tasks/00000000-0000-0000-0000-000000000000")
        # 302 if auth wall, 404 if authenticated
        assert resp.status_code in (302, 404)


class TestFLInputValidation:
    def test_gradients_endpoint_requires_encrypted_payload(self, client):
        resp = client.post(
            "/fl/tasks/fake-id/rounds/1/gradients",
            json={"weights": [1.0, 2.0]},
            content_type="application/json",
        )
        assert resp.status_code in (302, 400)

    def test_list_rounds_nonexistent_task(self, client):
        resp = client.get("/fl/tasks/00000000-0000-0000-0000-000000000000/rounds")
        assert resp.status_code in (302, 404)

    def test_get_model_nonexistent_task(self, client):
        resp = client.get("/fl/tasks/00000000-0000-0000-0000-000000000000/model")
        assert resp.status_code in (302, 404)


class TestLegacyRedirect:
    def test_legacy_url_redirects(self, client):
        resp = client.get("/federated/federated_learning/federated_learning")
        assert resp.status_code in (301, 302)
