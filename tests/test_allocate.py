from app.allocate import (
    allocate,
    is_viable_occupancy,
    mutual_pairs,
    one_way_requests,
    rank_students,
    room_score,
)


def test_merit_key_uses_merit_then_year_then_id():
    students = [
        {"id": 3, "merit": 90, "year": 2},
        {"id": 2, "merit": 90, "year": 3},
        {"id": 1, "merit": 90, "year": 3},
        {"id": 4, "merit": 80, "year": 4},
    ]

    ranked = rank_students(students)

    assert [s["id"] for s in ranked] == [1, 2, 3, 4]
    assert [s["rank"] for s in ranked] == [1, 2, 3, 4]


def test_mutual_pairs_requires_both_students_to_agree():
    students = [
        {"id": 1, "wants": [2]},
        {"id": 2, "wants": [1]},
        {"id": 3, "wants": [1]},
    ]

    assert mutual_pairs(students) == [(1, 2)]


def test_one_way_requests_are_reported():
    students = [
        {"id": 1, "name": "Asha", "wants": [2]},
        {"id": 2, "name": "Bina", "wants": [3]},
        {"id": 3, "name": "Charu", "wants": [2]},
    ]

    requests = one_way_requests(students)

    assert any(
        item["student"] == 1
        and item["wanted"] == 2
        and item["reason"] == "not_mutual"
        for item in requests
    )


def test_room_occupancy_rules():
    assert is_viable_occupancy(4, 0)
    assert is_viable_occupancy(4, 2)
    assert not is_viable_occupancy(4, 1)
    assert is_viable_occupancy(2, 1)
    assert not is_viable_occupancy(2, 3)


def test_matching_room_type_scores_higher():
    leader = {"room_type": "double", "floor_pref": 1}

    matching_room = {
        "id": 1, "room_type": "double", "floor": 2, "capacity": 2
    }
    other_room = {
        "id": 2, "room_type": "single", "floor": 1, "capacity": 1
    }

    assert room_score(matching_room, 1, leader) > room_score(
        other_room, 1, leader
    )


def test_allocation_places_every_student_deterministically():
    students = [
        {
            "id": 1, "name": "Asha", "merit": 95, "year": 3,
            "room_type": "double", "floor_pref": 1, "wants": [2],
        },
        {
            "id": 2, "name": "Bina", "merit": 90, "year": 2,
            "room_type": "double", "floor_pref": 1, "wants": [1],
        },
        {
            "id": 3, "name": "Charu", "merit": 80, "year": 1,
            "room_type": "single", "floor_pref": 0, "wants": [],
        },
    ]

    rooms = [
        {
            "id": 1, "code": "D-101", "room_type": "double",
            "floor": 1, "capacity": 2,
        },
        {
            "id": 2, "code": "S-101", "room_type": "single",
            "floor": 0, "capacity": 1,
        },
    ]

    first = allocate(students, rooms)
    second = allocate(students, rooms)

    assert first == second
    assert first["summary"]["students"] == 3
    assert first["summary"]["placed"] == 3
    assert not first["unplaced"]

    for room in first["rooms"]:
        assert room["filled"] <= room["capacity"]

    assignments = {item["student"]: item for item in first["assignments"]}
    assert assignments[1]["room"] == "D-101"
    assert assignments[2]["room"] == "D-101"
    assert assignments[3]["room"] == "S-101"


def test_allocation_progress_is_monotonic_and_finishes():
    students = [
        {
            "id": 1, "name": "Asha", "merit": 95, "year": 3,
            "room_type": "single", "floor_pref": 0, "wants": [],
        }
    ]
    rooms = [
        {
            "id": 1, "code": "S-101", "room_type": "single",
            "floor": 0, "capacity": 1,
        }
    ]

    progress = []
    allocate(students, rooms, progress=lambda done, total, msg:
             progress.append((done, total, msg)))

    done_values = [item[0] for item in progress]

    assert done_values == sorted(done_values)
    assert progress[-1][0] == progress[-1][1] == 5
    assert progress[-1][2] == "done"
