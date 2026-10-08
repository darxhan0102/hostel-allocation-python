# Hostel Room Allocation Engine

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/darxhan0102/hostel-allocation-python/tree/main.svg?style=shield)](https://circleci.com/gh/darxhan0102/hostel-allocation-python)
![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16.4-336791?logo=postgresql)
![Redis](https://img.shields.io/badge/Redis-7.4-DC382D?logo=redis)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)

A production-ready hostel room allocation service written in Python with FastAPI, backed by PostgreSQL and Redis. It allocates hostel rooms fairly, deterministically, and explainably based on student merit, seniority, mutual roommate choices, and room specifications.

---

## Table of Contents

- [Overview & Architecture](#overview--architecture)
- [The Allocation Algorithm ("The Hard Part")](#the-allocation-algorithm-the-hard-part)
  - [1. Total Ordering & Tie-Breaking](#1-total-ordering--tie-breaking)
  - [2. Mutual Requests vs. One-Way Requests](#2-mutual-requests-vs-one-way-requests)
  - [3. Group Formation & Fair Bumping](#3-group-formation--fair-bumping)
  - [4. Lonely Room Prevention & Viable Occupancy](#4-lonely-room-prevention--viable-occupancy)
  - [5. Explainability & Disappointment Tracking](#5-explainability--disappointment-tracking)
- [Technology Stack](#technology-stack)
- [Quick Start with Docker Compose](#quick-start-with-docker-compose)
- [API Reference](#api-reference)
- [Database & Migrations](#database--migrations)
- [Testing & Quality Assurance](#testing--quality-assurance)
- [CI/CD Pipeline (CircleCI)](#cicd-pipeline-circleci)
- [Production & Security Considerations](#production--security-considerations)

---

## Overview & Architecture

University room allocations present complex trade-offs: competing student preferences, varying room capacities, and interpersonal requests. This system treats the allocation problem as an explainable optimization with strict invariants:

```
                      +-----------------------------+
                      |       Client / Admin        |
                      +--------------+--------------+
                                     |
                                     | HTTP Requests (Port 8080)
                                     v
                      +-----------------------------+
                      |     FastAPI Web Service     |
                      |  - App User (UID 1001)      |
                      |  - Async Background Tasks   |
                      +-------+-------------+-------+
                              |             |
        Read / Write State    |             | Ephemeral Progress & Cache
        (Runs, Students, etc) |             | (TTL = 3600s)
                              v             v
       +------------------------+         +--------------------+
       | PostgreSQL 16.4        |         | Redis 7.4          |
       | - Persistent Storage   |         | - Run Progress     |
       | - Relational Integrity |         | - Live Run Polling |
       +------------------------+         +--------------------+
```

### Why Redis is Here
An allocation run over an entire student cohort is computationally non-trivial. Instead of holding an HTTP request open, `POST /allocate` responds with `202 Accepted` and a unique `run_id`. The work executes as an asynchronous background task. 

Redis stores real-time progress steps and messages using auto-expiring keys (`TTL = 3600s`). Every web worker can read or report progress without holding locks or repeatedly writing high-frequency state updates to PostgreSQL. Once complete, durable final records are written to PostgreSQL.

---

## The Allocation Algorithm ("The Hard Part")

The core allocator logic in [`app/allocate.py`](app/allocate.py) is implemented as pure, side-effect-free functions operating over in-memory data structures without network or database dependencies.

### 1. Total Ordering & Tie-Breaking
When resources are scarce, an ordering mechanism must be defensible and free of non-deterministic behavior.

The allocation uses a **strict total ordering**:
$$\text{Merit Key} = (-\text{merit}, -\text{year}, \text{id})$$

- **Merit:** Highest GPA / score sorts first.
- **Year (Seniority):** If merit is identical, senior students take priority.
- **Student ID:** If merit and year are identical, the lower numerical student ID wins.

> **Why this matters:** The ID tie-break guarantees that the algorithm never relies on system clocks, hash seeds, or arbitrary database row return order. Running `allocate()` multiple times on identical input produces byte-identical results.

### 2. Mutual Requests vs. One-Way Requests
> **A requests B, B requests C. Who gets paired?**

A one-way request is an unreciprocated wish. Pairing A with B without B's consent places a student into a room with someone they did not choose.
- **Rule:** Only **mutual pairs** ($A \leftrightarrow B$) form valid edges in the roommate graph.
- If Ishita asks for Janvi, but Janvi asks for Kabir, Ishita is not paired with Janvi and receives the reason `not_mutual`.
- **Serendipity Exception:** If Harsh requests Lakshmi (one-way), but their mutual friends lead them to share the same room anyway, Harsh is **not** reported as disappointed because his request was fulfilled in the end.

### 3. Group Formation & Fair Bumping
The roommate graph is decomposed into groups bounded by the largest room capacity ($C_{\text{max}} = 4$ for quads):
1. Traversal starts from the highest-ranked unplaced student.
2. The group expands outward to include their highest-ranked mutual neighbors until the room limit is reached.
3. **Bumping Outranked Members:** When 5 mutual friends seek a 4-bed room, the lowest-ranked candidate is bumped. The system logs:
   - `student`: The bumped student's ID.
   - `blocked_by`: The specific winning roommate whose rank squeezed them out.
   - `reason`: `"outranked"`.

### 4. Lonely Room Prevention & Viable Occupancy
Leaving a single occupant inside a 3-bed or 4-bed room wastes space and creates an isolating experience:
$$\text{is\_viable\_occupancy}(\text{capacity}, \text{filled}) = \neg (\text{filled} = 1 \land \text{capacity} \ge 3)$$

To eliminate lonely rooms, a deterministic two-phase repair pass (`_repair_lonely`) executes:
1. **Move Out:** Move the solitary student to the smallest available room with spare capacity.
2. **Move In (Donor Selection):** If no smaller rooms exist, transfer a roommate into the room. Donors are drawn from rooms with the fewest occupants (favoring solo students to avoid breaking mutual pairs), breaking ties with the lowest-ranked student.
3. If structural constraints make repair impossible, the student is explicitly flagged in `stranded`.

### 5. Explainability & Disappointment Tracking
Every student who does not receive their preferred room type, preferred floor, or requested roommate is provided an explicit explanation:
- `not_mutual`: The requested roommate did not list the student back.
- `outranked`: The requested group filled up with higher-ranked candidates.
- `no_room_large_enough`: Capacity was exhausted before the group could be placed.

---

## Technology Stack

- **Application:** Python 3.12, FastAPI, Uvicorn, Pydantic
- **Data Stores:** PostgreSQL 16.4, Redis 7.4
- **Database Driver:** Psycopg 3
- **Containerization:** Docker (Multi-stage / Layer-cached), Docker Compose v2
- **Testing:** Pytest, Pytest-Cov
- **Code Quality:** Ruff
- **CI/CD:** CircleCI

---

## Quick Start with Docker Compose

### Prerequisites
- Docker Engine 24+ and Docker Compose v2.

### 1. Build and Start All Services
```bash
docker compose up --build
```

This single command:
1. Starts **PostgreSQL 16.4** and **Redis 7.4** with health checks.
2. Executes the `migrate` service which applies all SQL files from [`migrations/`](migrations/) sequentially in filename order.
3. Builds and boots the FastAPI application container once migrations complete.

### 2. Verify System Health
```bash
curl http://localhost:8080/health
```

Expected response:
```json
{
  "status": "ok",
  "postgres": true,
  "redis": true
}
```

---

## API Reference

### Health Check
- **`GET /health`**
  - Returns connection status for both PostgreSQL and Redis independently.
  - Returns HTTP `200` if both are healthy, or HTTP `503` if either is down.

### Students & Preferences
- **`GET /students`**
  - Returns the roster ranked by merit key, existing mutual pairs, and active one-way requests.
- **`PUT /students/{id}/preferences`**
  - Update preferences for a student.
  - **Body:**
    ```json
    {
      "room_type": "double",
      "floor_pref": 1,
      "wants": [4, 5]
    }
    ```
  - Validation enforces: maximum of 2 roommate requests, valid student IDs, and prevents self-requests.

### Rooms
- **`GET /rooms`**
  - Lists all rooms, capacities, types, and current occupancy counts.

### Allocation Workflow
- **`POST /allocate`**
  - Initiates an allocation run in the background.
  - Returns HTTP `202 Accepted` with a tracking `run_id`:
    ```json
    {
      "run_id": "a1b2c3d4",
      "status": "queued",
      "poll": "/runs/a1b2c3d4"
    }
    ```
- **`GET /runs/{run_id}`**
  - Polls execution progress (`step`, `steps`, `message`, `status`). Reads from Redis with fallback to PostgreSQL once completed.
- **`GET /allocation`** or **`GET /allocation?run_id={run_id}`**
  - Returns the final allocation plan, assignments, satisfaction statistics, and disappointed student explanations.

---

## Database & Migrations

Migrations are stored in the [`migrations/`](migrations/) folder as plain SQL files:
- `001_schema.sql`: Table definitions for `students`, `rooms`, `roommate_requests`, `runs`, and `allocations`.
- `002_seed.sql`: Realistic seed data including student rankings and roommate request networks.

The Compose setup runs a dedicated ephemeral container using `psql -v ON_ERROR_STOP=1` against `migrations/*.sql` sorted alphabetically before the app service starts.

---

## Testing & Quality Assurance

### Unit Tests
The unit test suite validates pure logic in [`app/allocate.py`](app/allocate.py) with zero external dependencies (no DB, no network):
```bash
pytest tests/unit --cov=app.allocate --cov-report=term-missing --cov-fail-under=70
```

Coverage is maintained at **97%+**, validating:
- Strict total order ranking and ID-based tie breaking.
- Detection of reciprocal pairs vs. one-way requests.
- Five-friend group splitting and bumper assignment.
- Lonely room prevention logic across single, double, triple, and quad scenarios.
- Deterministic reproducibility under inverted input ordering.

### Integration Tests
Integration tests test the live FastAPI application against running PostgreSQL and Redis instances:
```bash
pytest tests/integration -v
```

Tests cover health reporting, preference mutations, end-to-end background allocation execution, and plan retrieval.

### Linting
```bash
ruff check .
```

---

## CI/CD Pipeline (CircleCI)

The automated CircleCI pipeline ([`.circleci/config.yml`](.circleci/config.yml)) executes on every commit:

```
[ Git Push ]
     │
     ├─► lint (Ruff syntax & style checks)
     │
     ├─► unit-tests (pytest with --cov-fail-under=70)
     │
     ├─► integration-tests (FastAPI against Postgres 16 & Redis 7 service containers)
     │
     ├─► secret-scan (Detect uncommitted secrets or credentials)
     │
     └─► build-image (Docker image build verification)
```

All 5 jobs run in parallel or dependent stages, ensuring code quality, test coverage, integration stability, and container integrity before release.

---

## Production & Security Considerations

1. **Non-Root Execution:** The Dockerfile creates and runs the application under a dedicated unprivileged user (`appuser`, UID `1001`).
2. **Layer Caching:** Dependencies in `requirements.txt` are installed before copying application source code to optimize Docker layer caching.
3. **Service Decoupling:** Long-running tasks execute in the background with Redis progress tracking, preventing HTTP connection starvation.
4. **Reproducibility:** Pinned dependencies and pinned container images (`python:3.12.7-slim`, `postgres:16.4`, `redis:7.4`) eliminate drift between environments.
