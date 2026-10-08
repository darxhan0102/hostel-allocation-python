# Hostel Room Allocation

**Language:** Python (FastAPI) &nbsp;|&nbsp; **Needs:** Postgres + Redis

This is a **starter**. The application already works. Your job is everything
that gets it building, tested and running in CI.

---

## You do not need Python installed

You will build this into a container, and the container brings its own
Python 3.12. You are not being asked to extend the app — you are being asked
to ship it.

---

## 1. What this app needs

| | |
|---|---|
| **Runtime** | Python 3.12 |
| **Install dependencies** | `pip install -r requirements.txt` |
| **Start the app** | `uvicorn app.main:app --host 0.0.0.0 --port 8080` |
| **Listens on** | port 8080, bound to `0.0.0.0` |
| **Environment variables** | `DATABASE_URL`, `REDIS_URL` |
| **Needs running first** | Postgres, Redis, and the migrations applied |

### What it does

Students submit a room type, a floor, and up to two people they would like to live with. The allocator honours only MUTUAL roommate requests, ranks everybody by merit and seniority, fills rooms best-first, and refuses to leave anybody alone in a four-bed room. Every student who does not get what they asked for comes back with a reason.

### Endpoints

```
GET  /health
GET  /students                      roster, mutual pairs, one-way requests
GET  /rooms                         every room and how full it is
PUT  /students/{id}/preferences  {"room_type":"double","floor_pref":1,"wants":[4,5]}
POST /allocate                      start a run, returns a run_id
GET  /runs/{run_id}                 progress while it runs, result when it is done
GET  /allocation?run_id=...         the stored plan
```

`/health` reports Postgres and Redis **separately**. If it says
`postgres: false` the app started fine and your compose wiring is wrong —
do not go looking in the application code.

### Migrations

`migrations/` holds `.sql` files applied **in filename order** before the app
starts. They create the tables and insert sample data. A container running
`psql` over them in order is enough; you do not need a migration tool.

---

## 2. What you must write

| File | What it has to do |
|---|---|
| `Dockerfile` | Install dependencies **before** copying source, pin the base image, do not run as root. |
| `docker-compose.yml` | App + Postgres + Redis + a migration step, one `docker compose up`. |
| `.circleci/config.yml` | lint → unit tests → integration tests → secret scan → image build |
| Unit tests | For `app/allocate.py`. No database, no network. |
| Integration tests | Against a real Postgres and Redis as CircleCI service containers. |

Then push your image to **your own Docker Hub account**, tagged `:1.0`.

### When it works

```bash
docker compose up --build
curl localhost:8080/health
```

```json
{"status":"ok","postgres":true,"redis":true}
```

---

## Where the marks are

`app/allocate.py` is **pure logic** — plain functions over plain data, no
database and no HTTP. Start your tests there. Use pytest:
`pytest --cov=app --cov-report=term-missing`. Minimum 70%.

`form_groups` is where the marks are. Seed five mutually-agreed friends and a largest room of four, then assert on WHICH one is bumped and what `blocked_by` says. Then run `allocate` twice on the same input and assert the two results are identical - if they are not, your ordering has a tie in it somewhere.

## Why Redis is here

An allocation for a real hostel is not a request-sized job, so it runs in the background and the HTTP request that started it is long gone before it finishes. The progress has to live somewhere every web worker can read, and it has to clean itself up when nobody comes back to look. That is a TTL key in Redis, not a table you would then have to sweep.

## The hard part

**A requests B, B requests C. Somebody has to be disappointed, and the rule for who must be defensible.** A one-way request is a crush, not an agreement - honour it and you put somebody in a room with a person who never chose them. So only mutual pairs form groups, and when two mutual groups compete for the same person, rank decides. Write down your ranking rule, make sure it is total (no ties can survive), and make sure every disappointed student can be told who beat them and why.

Write your answer in your README. It is worth more marks than the feature.

---

## Getting unstuck

| Symptom | Almost always |
|---|---|
| `/health` says `postgres: false` | Wrong hostname. In compose the host is the **service name**, not `localhost`. |
| Page will not load, logs fine | No `ports:` mapping, or bound to `127.0.0.1` not `0.0.0.0`. |
| `relation "..." does not exist` | Migrations did not run, or the app started before they finished. |
| Build takes minutes each time | `COPY . .` is above your dependency install. |
| CI cannot reach the database | In CircleCI service containers the host **is** `localhost` — opposite of compose. |
