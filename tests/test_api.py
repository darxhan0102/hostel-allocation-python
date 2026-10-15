
import os

import httpx


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")


def test_health_checks_postgres_and_redis():
    response = httpx.get(f"{BASE_URL}/health", timeout=10)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["postgres"] is True
    assert data["redis"] is True


def test_students_endpoint_returns_records():
    response = httpx.get(f"{BASE_URL}/students", timeout=10)

    assert response.status_code == 200
    data = response.json()
    assert "students" in data
    assert len(data["students"]) > 0


def test_rooms_endpoint_returns_records():
    response = httpx.get(f"{BASE_URL}/rooms", timeout=10)

    assert response.status_code == 200
    data = response.json()
    assert "rooms" in data
    assert len(data["rooms"]) > 0


def test_invalid_room_type_is_rejected():
    response = httpx.put(
        f"{BASE_URL}/students/1/preferences",
        json={"room_type": "penthouse", "wants": []},
        timeout=10,
    )

    assert response.status_code == 400
    assert "room_type must be" in response.json()["detail"]

