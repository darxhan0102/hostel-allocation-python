"""Integration tests: the real app, a real Postgres and a real Redis."""
import os
import time

import pytest
import redis
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def run_allocation(client):
    r = client.post("/allocate")
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    for _ in range(60):
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in ("done", "failed"):
            return run_id, body
        time.sleep(0.5)
    pytest.fail("allocation did not finish in 30 seconds")


def test_health_reports_postgres_and_redis_up(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "postgres": True, "redis": True}


def test_students_and_rooms_come_from_the_migrations(client):
    students = client.get("/students").json()
    assert len(students["students"]) > 0
    assert all("rank" in s for s in students["students"])
    assert len(client.get("/rooms").json()["rooms"]) > 0


def test_preferences_for_unknown_student_is_404(client):
    r = client.put("/students/999999/preferences", json={"wants": []})
    assert r.status_code == 404


def test_preferences_validation(client):
    sid = client.get("/students").json()["students"][0]["id"]
    assert client.put(f"/students/{sid}/preferences", json={"wants": [sid]}).status_code == 400
    assert client.put(f"/students/{sid}/preferences",
                      json={"wants": [9001, 9002, 9003]}).status_code == 400
    assert client.put(f"/students/{sid}/preferences",
                      json={"room_type": "palace"}).status_code == 400


def test_two_matching_requests_become_a_mutual_pair(client):
    rows = client.get("/students").json()["students"]
    a, b = sorted(s["id"] for s in rows[:2])
    names = {s["id"]: s["name"] for s in rows}
    assert client.put(f"/students/{a}/preferences", json={"wants": [b]}).status_code == 200
    assert client.put(f"/students/{b}/preferences", json={"wants": [a]}).status_code == 200
    pairs = client.get("/students").json()["mutual_pairs"]
    assert {"a": names[a], "b": names[b]} in pairs


def test_unknown_run_is_404(client):
    assert client.get("/runs/doesnotexist").status_code == 404


def test_allocation_runs_and_progress_lives_in_redis_with_a_ttl(client):
    run_id, body = run_allocation(client)
    assert body["status"] == "done"

    total = len(client.get("/students").json()["students"])
    assert len(body["result"]["assignments"]) + len(body["result"]["unplaced"]) == total

    stored = client.get(f"/allocation?run_id={run_id}")
    assert stored.status_code == 200
    assert len(stored.json()["allocation"]) == len(body["result"]["assignments"])

    r = redis.Redis.from_url(os.environ["REDIS_URL"])
    keys = list(r.scan_iter(f"*{run_id}*"))
    assert keys, "progress should be stored in Redis"
    assert all(0 < r.ttl(k) <= 3600 for k in keys)


def test_two_runs_on_the_same_data_give_the_same_plan(client):
    _, first = run_allocation(client)
    _, second = run_allocation(client)
    assert first["result"]["assignments"] == second["result"]["assignments"]
