"""Tests for demo API routes."""

import pytest


def test_demo_health_check(client):
    """Test demo health endpoint returns healthy status."""
    response = client.get("/api/demo/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "demo-api"


def test_demo_list_datasets(client):
    """Test demo datasets listing."""
    response = client.get("/api/demo/datasets")
    assert response.status_code == 200
    data = response.get_json()
    assert "datasets" in data
    assert "count" in data


def test_demo_query_with_valid_params(client):
    """Test demo query with valid parameters."""
    response = client.get("/api/demo/query?dataset=gut_microbiome&group_by=organism&measure=abundance")
    assert response.status_code == 200
    data = response.get_json()
    assert "results" in data
    assert data["dataset"] == "gut_microbiome"


def test_demo_query_with_invalid_dataset(client):
    """Test demo query with invalid dataset returns 400."""
    response = client.get("/api/demo/query?dataset=invalid_dataset")
    assert response.status_code == 400


def test_demo_query_with_invalid_group_by(client):
    """Test demo query with invalid group_by returns 400."""
    response = client.get("/api/demo/query?dataset=gut_microbiome&group_by=invalid")
    assert response.status_code == 400