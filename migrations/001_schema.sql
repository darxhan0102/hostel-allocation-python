CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    year INT NOT NULL DEFAULT 1 CHECK (year BETWEEN 1 AND 5),
    merit NUMERIC(4,2) NOT NULL DEFAULT 0 CHECK (merit >= 0 AND merit <= 10),
    room_type TEXT NOT NULL DEFAULT 'double',
    floor_pref INT);

CREATE TABLE IF NOT EXISTS roommate_requests (
    student_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    wanted_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    PRIMARY KEY (student_id, wanted_id),
    CHECK (student_id <> wanted_id));

CREATE TABLE IF NOT EXISTS rooms (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    block TEXT NOT NULL DEFAULT 'A',
    floor INT NOT NULL DEFAULT 0,
    room_type TEXT NOT NULL,
    capacity INT NOT NULL CHECK (capacity BETWEEN 1 AND 4));

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    placed INT NOT NULL DEFAULT 0,
    unplaced INT NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS allocations (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    student_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, student_id));
CREATE INDEX IF NOT EXISTS allocations_room ON allocations (run_id, room_id);
