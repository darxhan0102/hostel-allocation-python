from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from . import cache, db
from .allocate import (
    MAX_ROOMMATE_REQUESTS,
    AllocationError,
    allocate,
    mutual_pairs,
    one_way_requests,
    rank_students,
)

app = FastAPI(title="hostel-allocation")

STATIC_INDEX = Path(__file__).parent / "static" / "index.html"
RUN_TTL = 3600


@app.get("/", response_class=HTMLResponse)
def index():
    if STATIC_INDEX.exists():
        return HTMLResponse(STATIC_INDEX.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Hostel Room Allocation Engine</h1>")


@app.get("/health")
def health():
    out = {"status": "ok", "postgres": False, "redis": False}
    try:
        db.query("SELECT 1")
        out["postgres"] = True
    except Exception as e:
        out["pg_error"] = str(e)
    try:
        cache.client().ping()
        out["redis"] = True
    except Exception as e:
        out["redis_error"] = str(e)
    return out if out["postgres"] and out["redis"] else JSONResponse(out, status_code=503)


def _students():
    rows = db.query(
        "SELECT s.id, s.name, s.year, s.merit, s.room_type, s.floor_pref,"
        " coalesce(array_agg(r.wanted_id) FILTER (WHERE r.wanted_id IS NOT NULL),"
        " '{}') AS wants"
        " FROM students s LEFT JOIN roommate_requests r ON r.student_id = s.id"
        " GROUP BY s.id ORDER BY s.id")
    return [{**r, "merit": float(r["merit"]), "wants": list(r["wants"])} for r in rows]


def _rooms():
    return [dict(r) for r in db.query(
        "SELECT id, code, block, floor, room_type, capacity FROM rooms ORDER BY id")]


@app.get("/students")
def students():
    rows = rank_students(_students())
    pairs = mutual_pairs(rows)
    names = {s["id"]: s["name"] for s in rows}
    return {"students": rows,
            "mutual_pairs": [{"a": names[a], "b": names[b]} for a, b in pairs],
            "one_way_requests": one_way_requests(rows)}


@app.get("/rooms")
def rooms():
    return {"rooms": db.query(
        "SELECT r.id, r.code, r.block, r.floor, r.room_type, r.capacity,"
        " (SELECT count(*) FROM allocations a WHERE a.room_id = r.id"
        "  AND a.run_id = (SELECT id FROM runs WHERE status='done'"
        "                  ORDER BY finished_at DESC LIMIT 1)) AS filled"
        " FROM rooms r ORDER BY r.code")}


@app.put("/students/{sid}/preferences")
def preferences(sid: int, payload: dict = Body(...)):
    """Set one student's room type, floor and roommate wishes."""
    who = db.one("SELECT id, name FROM students WHERE id=%s", (sid,))
    if not who:
        raise HTTPException(404, "no such student")

    room_type = str(payload.get("room_type", "")).strip().lower()
    if room_type and room_type not in ("single", "double", "triple", "quad"):
        raise HTTPException(400, "room_type must be single, double, triple or quad")

    wants = payload.get("wants", [])
    if not isinstance(wants, list):
        raise HTTPException(400, "wants must be a list of student ids")
    if len(wants) > MAX_ROOMMATE_REQUESTS:
        raise HTTPException(400, f"at most {MAX_ROOMMATE_REQUESTS} roommate requests")
    try:
        wants = [int(w) for w in wants]
    except (TypeError, ValueError):
        raise HTTPException(400, "wants must be student ids")
    if sid in wants:
        raise HTTPException(400, "you cannot request yourself as a roommate")
    if len(set(wants)) != len(wants):
        raise HTTPException(400, "the same roommate twice is still one roommate")
    for w in wants:
        if not db.one("SELECT id FROM students WHERE id=%s", (w,)):
            raise HTTPException(404, f"no student with id {w}")

    floor_pref = payload.get("floor_pref")
    with db.connect() as conn, conn.cursor() as cur:
        if room_type:
            cur.execute("UPDATE students SET room_type=%s WHERE id=%s", (room_type, sid))
        if floor_pref is not None:
            cur.execute("UPDATE students SET floor_pref=%s WHERE id=%s", (int(floor_pref), sid))
        cur.execute("DELETE FROM roommate_requests WHERE student_id=%s", (sid,))
        for w in wants:
            cur.execute("INSERT INTO roommate_requests (student_id, wanted_id)"
                        " VALUES (%s,%s)", (sid, w))
    return {"student": sid, "name": who["name"], "room_type": room_type or None,
            "floor_pref": floor_pref, "wants": wants}


def _run(run_id):
    """The allocation itself. Slow enough in a real hostel to need a run id."""
    def progress(done, total, message):
        cache.set_json(f"run:{run_id}",
                       {"run_id": run_id, "status": "running", "step": done,
                        "steps": total, "message": message}, ttl=RUN_TTL)

    try:
        result = allocate(_students(), _rooms(), progress=progress)
    except Exception as e:  # noqa: BLE001 - a background task must never die silently
        # Record the failure in both places a caller might look.
        kind = "bad input" if isinstance(e, AllocationError) else "unexpected"
        cache.set_json(f"run:{run_id}", {"run_id": run_id, "status": "failed",
                                         "error": f"{kind}: {e}"}, ttl=RUN_TTL)
        db.query("UPDATE runs SET status='failed', finished_at=now() WHERE id=%s",
                 (run_id,), fetch=False)
        return

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM allocations WHERE run_id=%s", (run_id,))
        for a in result["assignments"]:
            cur.execute("INSERT INTO allocations (run_id, student_id, room_id)"
                        " VALUES (%s,%s,%s)", (run_id, a["student"], a["room_id"]))
        cur.execute("UPDATE runs SET status='done', finished_at=now(),"
                    " placed=%s, unplaced=%s WHERE id=%s",
                    (len(result["assignments"]), len(result["unplaced"]), run_id))

    cache.set_json(f"run:{run_id}", {"run_id": run_id, "status": "done",
                                     "step": 5, "steps": 5, "message": "done",
                                     "result": result}, ttl=RUN_TTL)


@app.post("/allocate", status_code=202)
def start_allocation(tasks: BackgroundTasks):
    """Kick off an allocation and hand back a run id to poll.

    Redis earns its place here. The allocation runs in the background, so the
    HTTP request that started it is long gone by the time it finishes. The
    progress has to live somewhere every web worker can see it, and it has to
    expire by itself when nobody comes back to look.
    """
    run_id = str(uuid4())[:8]
    db.query("INSERT INTO runs (id, status) VALUES (%s,'running')", (run_id,), fetch=False)
    cache.set_json(f"run:{run_id}", {"run_id": run_id, "status": "queued",
                                     "step": 0, "steps": 5,
                                     "message": "queued"}, ttl=RUN_TTL)
    tasks.add_task(_run, run_id)
    return {"run_id": run_id, "status": "queued", "poll": f"/runs/{run_id}"}


@app.get("/runs/{run_id}")
def run_status(run_id: str):
    live = cache.get_json(f"run:{run_id}")
    if live:
        return live
    row = db.one("SELECT id, status, started_at, finished_at, placed, unplaced"
                 " FROM runs WHERE id=%s", (run_id,))
    if not row:
        raise HTTPException(404, "no such run")
    return {**row, "note": "progress has expired from the cache; this is the"
                           " durable record"}


@app.get("/allocation")
def allocation(run_id: str = ""):
    """The stored plan from a finished run."""
    if not run_id:
        row = db.one("SELECT id FROM runs WHERE status='done'"
                     " ORDER BY finished_at DESC LIMIT 1")
        if not row:
            raise HTTPException(404, "no allocation has finished yet")
        run_id = row["id"]
    rows = db.query(
        "SELECT s.name, s.merit, s.year, r.code AS room, r.room_type, r.floor,"
        " s.room_type AS wanted_type, s.floor_pref"
        " FROM allocations a JOIN students s ON s.id=a.student_id"
        " JOIN rooms r ON r.id=a.room_id WHERE a.run_id=%s"
        " ORDER BY r.code, s.name", (run_id,))
    if not rows:
        raise HTTPException(404, "that run has no allocations")
    return {"run_id": run_id,
            "allocation": [{**r, "merit": float(r["merit"]),
                            "got_room_type": r["room_type"] == r["wanted_type"],
                            "got_floor": r["floor"] == r["floor_pref"]} for r in rows]}
