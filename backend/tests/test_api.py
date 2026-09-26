"""Tests for FastAPI endpoints."""

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "VibeShorts" in data["app"]


def test_get_nonexistent_job():
    response = client.get("/api/v1/jobs/nonexistent_123/status")
    assert response.status_code == 404
