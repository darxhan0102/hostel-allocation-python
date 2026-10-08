"""The sample data from migrations/, run through the pure logic."""
import json

from app.allocate import allocate, form_groups, mutual_pairs, one_way_requests, rank_students

STUDENTS = [
    (1, "Aarav Mehta", 3, 9.40, "double", 1),
    (2, "Bhavya Rao", 3, 9.10, "double", 1),
    (3, "Ishita Nair", 2, 8.90, "double", 2),
    (4, "Janvi Kulkarni", 2, 8.70, "double", 2),
    (5, "Kabir Shah", 2, 8.60, "double", 2),
    (6, "Devansh Gupta", 4, 8.50, "triple", 0),
    (7, "Eshan Pillai", 4, 8.30, "triple", 0),
    (8, "Farhan Qureshi", 4, 8.20, "triple", 0),
    (9, "Gauri Deshpande", 1, 7.90, "quad", 3),
    (10, "Harsh Vardhan", 1, 7.80, "quad", 3),
    (11, "Lakshmi Iyer", 1, 7.70, "quad", 3),
    (12, "Manan Joshi", 1, 7.60, "quad", 3),
    (13, "Nikhil Bose", 1, 7.50, "quad", 3),
    (14, "Oviya Raman", 2, 7.20, "single", 1),
    (15, "Pranav Sethi", 2, 7.20, "single", 1),
    (16, "Qamar Ali", 3, 7.00, "double", 0),
    (17, "Riya Chatterjee", 1, 6.80, "double", 2),
    (18, "Sahil Dubey", 2, 6.50, "triple", 3),
    (19, "Tanvi Menon", 1, 6.20, "quad", 1),
    (20, "Umesh Kadam", 1, 5.90, "quad", 2),
]

REQUESTS = [
    (1, 2), (2, 1),
    (3, 4), (4, 5), (5, 4),
    (6, 7), (6, 8), (7, 6), (7, 8), (8, 6), (8, 7),
    (9, 10), (9, 11), (10, 9), (10, 11), (11, 9), (11, 12),
    (12, 11), (12, 13), (13, 12), (13, 9),
    (14, 15), (15, 14),
]

ROOMS = [
    (1, "A-001", "A", 0, "triple", 3), (2, "A-002", "A", 0, "triple", 3),
    (3, "A-101", "A", 1, "double", 2), (4, "A-102", "A", 1, "double", 2),
    (5, "A-103", "A", 1, "single", 1), (6, "B-201", "B", 2, "double", 2),
    (7, "B-202", "B", 2, "double", 2), (8, "B-203", "B", 2, "single", 1),
    (9, "C-301", "C", 3, "quad", 4), (10, "C-302", "C", 3, "quad", 4),
]


def seed_students():
    wants = {}
    for a, b in REQUESTS:
        wants.setdefault(a, []).append(b)
    return [{"id": i, "name": n, "year": y, "merit": m, "room_type": t,
             "floor_pref": f, "wants": wants.get(i, [])}
            for i, n, y, m, t, f in STUDENTS]


def seed_rooms():
    return [{"id": i, "code": c, "block": b, "floor": f, "room_type": t, "capacity": cap}
            for i, c, b, f, t, cap in ROOMS]


def test_seed_mutual_pairs():
    assert mutual_pairs(seed_students()) == [
        (1, 2), (4, 5), (6, 7), (6, 8), (7, 8),
        (9, 10), (9, 11), (11, 12), (12, 13), (14, 15)]


def test_seed_chain_ishita_is_not_mutual():
    out = one_way_requests(seed_students())
    assert {"student": 3, "wanted": 4, "reason": "not_mutual"}.items() <= \
        next(d for d in out if d["student"] == 3).items()


def test_seed_five_friends_nikhil_is_bumped_by_manan():
    groups, bumped = form_groups(rank_students(seed_students()), 4)
    assert [9, 10, 11, 12] in groups
    assert len(bumped) == 1
    assert bumped[0]["student"] == 13
    assert bumped[0]["blocked_by"] == 12
    assert bumped[0]["reason"] == "outranked"
    assert bumped[0]["group"] == [9, 10, 11, 12]


def test_seed_identical_merit_and_year_is_split_by_id():
    ranked = rank_students(seed_students())
    rank = {s["id"]: s["rank"] for s in ranked}
    assert rank[14] < rank[15]


def test_seed_full_plan():
    result = allocate(seed_students(), seed_rooms())
    assert len(result["assignments"]) == 20
    assert result["unplaced"] == []
    assert result["stranded"] == []
    assert result["moved_to_avoid_lonely_room"] == []
    for r in result["rooms"]:
        assert r["filled"] <= r["capacity"]
        assert not (r["capacity"] >= 3 and r["filled"] == 1)
    got = {(d["student"], d["reason"]) for d in result["disappointed"]}
    assert got == {(3, "not_mutual"), (13, "not_mutual"), (13, "outranked")}
    assert all(d["reason"] for d in result["disappointed"])


def test_seed_allocation_is_identical_every_time():
    a = json.dumps(allocate(seed_students(), seed_rooms()), sort_keys=True)
    b = json.dumps(allocate(seed_students(), seed_rooms()), sort_keys=True)
    c = json.dumps(allocate(list(reversed(seed_students())), list(reversed(seed_rooms()))),
                   sort_keys=True)
    assert a == b == c
