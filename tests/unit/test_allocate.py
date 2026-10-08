"""Unit tests for app/allocate.py - pure logic, no database, no network."""
import itertools
import json

import pytest

from app.allocate import (
    AllocationError,
    _repair_lonely,
    adjacency,
    allocate,
    capacity_of,
    choose_room,
    form_groups,
    is_viable_occupancy,
    merit_key,
    mutual_pairs,
    one_way_requests,
    rank_students,
    room_score,
)

SIZES = {"single": 1, "double": 2, "triple": 3, "quad": 4}


def S(sid, merit=50.0, year=1, wants=(), room_type="double", floor_pref=None):
    return {"id": sid, "name": f"S{sid}", "merit": merit, "year": year,
            "wants": list(wants), "room_type": room_type, "floor_pref": floor_pref}


def R(rid, room_type="double", floor=1):
    return {"id": rid, "code": f"R{rid}", "block": "A", "floor": floor,
            "room_type": room_type, "capacity": SIZES[room_type]}


def room_state(rid, cap, occupants):
    return {"id": rid, "code": f"R{rid}", "capacity": cap, "occupants": list(occupants)}


def five_cycle(merits):
    """Five students in a ring, each asking for both neighbours: 1-2-3-4-5-1."""
    wants = {1: [2, 5], 2: [1, 3], 3: [2, 4], 4: [3, 5], 5: [4, 1]}
    return [S(i, merits[i - 1], wants=wants[i]) for i in range(1, 6)]


def big_hostel():
    wants = {1: [2], 2: [1], 3: [4, 5], 4: [3, 5], 5: [3, 4], 6: [7], 7: [8], 9: [1]}
    students = [S(i, merit=100 - i, wants=wants.get(i, [])) for i in range(1, 11)]
    rooms = [R(1, "quad"), R(2, "quad"), R(3, "double"), R(4, "double")]
    return students, rooms


# ---------------------------------------------------------------- ranking

def test_higher_merit_sorts_first():
    assert merit_key(S(1, merit=90)) < merit_key(S(2, merit=80))


def test_equal_merit_falls_to_year_then_id():
    ranked = rank_students([S(3, 80, 2), S(1, 80, 2), S(2, 80, 3)])
    assert [s["id"] for s in ranked] == [2, 1, 3]
    assert [s["rank"] for s in ranked] == [1, 2, 3]


def test_ranking_is_total_whatever_the_input_order():
    students = [S(1, 80, 2), S(2, 80, 2), S(3, 80, 2), S(4, 90, 1)]
    keys = [merit_key(s) for s in students]
    assert len(set(keys)) == len(keys)
    orders = {tuple(s["id"] for s in rank_students(list(p)))
              for p in itertools.permutations(students)}
    assert orders == {(4, 1, 2, 3)}


# ------------------------------------------------------- mutual requests

def test_one_way_request_makes_no_pair():
    assert mutual_pairs([S(1, wants=[2]), S(2, wants=[3]), S(3)]) == []


def test_mutual_request_makes_exactly_one_pair():
    assert mutual_pairs([S(1, wants=[2]), S(2, wants=[1])]) == [(1, 2)]


def test_self_request_and_unknown_student_make_nothing():
    assert mutual_pairs([S(1, wants=[1, 99])]) == []


def test_chain_only_the_mutual_part_pairs():
    chain = [S(1, wants=[2]), S(2, wants=[3]), S(3, wants=[2])]
    assert mutual_pairs(chain) == [(2, 3)]
    assert adjacency(chain) == {1: set(), 2: {3}, 3: {2}}


def test_one_way_requests_reports_not_mutual():
    chain = [S(1, wants=[2]), S(2, wants=[3]), S(3)]
    out = one_way_requests(chain)
    assert [(d["student"], d["wanted"], d["reason"]) for d in out] == [
        (1, 2, "not_mutual"), (2, 3, "not_mutual")]


def test_one_way_requests_reports_missing_student():
    out = one_way_requests([S(1, wants=[99])])
    assert out[0]["reason"] == "no_such_student"


# ------------------------------------------------------------ form_groups

def test_mutual_triple_is_one_group_nobody_bumped():
    ranked = rank_students([S(1, wants=[2, 3]), S(2, wants=[1, 3]), S(3, wants=[1, 2])])
    groups, bumped = form_groups(ranked, 4)
    assert groups == [[1, 2, 3]]
    assert bumped == []


def test_no_mutual_requests_gives_singletons():
    ranked = rank_students([S(1, 90, wants=[2]), S(2, 80, wants=[3]), S(3, 70)])
    groups, bumped = form_groups(ranked, 4)
    assert groups == [[1], [2], [3]]
    assert bumped == []


def test_five_friends_largest_room_four_bumps_the_right_one():
    ranked = rank_students(five_cycle([90, 80, 70, 60, 50]))
    groups, bumped = form_groups(ranked, 4)
    assert groups == [[1, 2, 3, 4], [5]]
    assert len(bumped) == 1
    assert bumped[0]["student"] == 5
    assert bumped[0]["blocked_by"] == 1      # best-ranked member who 5 asked for
    assert bumped[0]["reason"] == "outranked"
    assert bumped[0]["group"] == [1, 2, 3, 4]


def test_rank_decides_who_is_bumped():
    ranked = rank_students(five_cycle([50, 60, 70, 80, 90]))
    groups, bumped = form_groups(ranked, 4)
    assert groups == [[5, 4, 3, 2], [1]]
    assert bumped[0]["student"] == 1
    assert bumped[0]["blocked_by"] == 5


def test_form_groups_is_deterministic_even_with_all_ties():
    students = five_cycle([70, 70, 70, 70, 70])
    first = form_groups(rank_students(students), 4)
    second = form_groups(rank_students(students), 4)
    reversed_input = form_groups(rank_students(list(reversed(students))), 4)
    assert first == second == reversed_input


def test_form_groups_rejects_zero_size_rooms():
    with pytest.raises(AllocationError):
        form_groups(rank_students([S(1)]), 0)


# ----------------------------------------------------------------- rooms

def test_capacity_of():
    assert capacity_of({"capacity": 3}) == 3
    assert capacity_of({"room_type": "Quad"}) == 4
    with pytest.raises(AllocationError):
        capacity_of({"room_type": "palace"})


@pytest.mark.parametrize("cap,filled,ok", [
    (4, 1, False), (1, 1, True), (2, 1, True), (3, 1, False),
    (4, 0, True), (4, 4, True), (2, 3, False),
])
def test_is_viable_occupancy(cap, filled, ok):
    assert is_viable_occupancy(cap, filled) is ok


def test_room_score_room_type_beats_floor():
    leader = {"room_type": "double", "floor_pref": 1}
    right_type = {"room_type": "double", "floor": 2, "capacity": 2}
    right_floor = {"room_type": "triple", "floor": 1, "capacity": 2}
    assert room_score(right_type, 2, leader) > room_score(right_floor, 2, leader)


def test_room_score_tight_fit_beats_loose_fit():
    leader = {"room_type": "double"}
    tight = {"room_type": "double", "capacity": 2}
    loose = {"room_type": "double", "capacity": 3}
    assert room_score(tight, 2, leader) > room_score(loose, 2, leader)


def test_room_score_none_when_group_does_not_fit():
    assert room_score({"room_type": "double", "capacity": 2}, 3, {}) is None


def test_lone_student_does_not_score_an_empty_quad_highest():
    leader = {"room_type": "quad"}          # even if they asked for a quad
    quad = {"room_type": "quad", "capacity": 4}
    double = {"room_type": "double", "capacity": 2}
    assert room_score(quad, 1, leader) < room_score(double, 1, leader)


def test_topping_up_a_part_full_room_beats_opening_a_new_one():
    leader = {"room_type": "quad"}
    quad = {"room_type": "quad", "capacity": 4}
    assert room_score(quad, 2, leader, occupied=2) > room_score(quad, 2, leader, occupied=0)


def test_choose_room_breaks_ties_on_lowest_id():
    state = [{"id": 5, "room_type": "double", "floor": 1, "capacity": 2, "occupants": []},
             {"id": 3, "room_type": "double", "floor": 1, "capacity": 2, "occupants": []}]
    assert choose_room(state, 1, {"room_type": "double"})["id"] == 3


def test_choose_room_none_when_everything_is_full():
    state = [{"id": 1, "room_type": "double", "floor": 1, "capacity": 2, "occupants": [1, 2]}]
    assert choose_room(state, 1, {"room_type": "double"}) is None


# --------------------------------------------------------- _repair_lonely

def test_repair_moves_lonely_student_to_a_smaller_room():
    state = [room_state(1, 4, [10]), room_state(2, 2, [])]
    moved, stranded = _repair_lonely(state, {10: 1})
    assert [m["student"] for m in moved] == [10]
    assert moved[0]["to"] == "R2"
    assert state[0]["occupants"] == []
    assert state[1]["occupants"] == [10]
    assert stranded == []


def test_repair_brings_the_lowest_ranked_donor_in_when_nowhere_to_move():
    state = [room_state(1, 4, [10]), room_state(2, 2, [20, 21])]
    moved, stranded = _repair_lonely(state, {10: 1, 20: 2, 21: 3})
    assert moved[0]["student"] == 21         # rank 3 = lowest ranked, so 21 moves
    assert (moved[0]["from"], moved[0]["to"]) == ("R2", "R1")
    assert state[0]["occupants"] == [10, 21]
    assert state[1]["occupants"] == [20]
    assert stranded == []


def test_repair_reports_stranded_when_there_is_no_fix():
    state = [room_state(1, 4, [10]), room_state(2, 4, [])]
    moved, stranded = _repair_lonely(state, {10: 1})
    assert moved == []
    assert stranded[0]["student"] == 10
    assert stranded[0]["room"] == "R1"


# --------------------------------------------------------------- allocate

def test_allocate_needs_students_and_rooms():
    with pytest.raises(AllocationError):
        allocate([], [R(1)])
    with pytest.raises(AllocationError):
        allocate([S(1)], [])


def test_chain_disappoints_the_one_nobody_asked_back():
    students = [S(1, 60, wants=[2]), S(2, 90, wants=[3]), S(3, 80, wants=[2])]
    result = allocate(students, [R(1), R(2)])
    rooms = {a["student"]: a["room"] for a in result["assignments"]}
    assert rooms[2] == rooms[3]
    assert rooms[1] != rooms[2]
    assert len(result["disappointed"]) == 1
    d = result["disappointed"][0]
    assert (d["student"], d["wanted"], d["reason"]) == (1, 2, "not_mutual")


def test_one_way_request_that_was_satisfied_is_not_reported():
    # Harsh (1) asks for Lakshmi (2); she never asks back, but they share the room.
    students = [S(1, 50, wants=[2]), S(2, 90)]
    result = allocate(students, [R(1)])
    rooms = {a["student"]: a["room"] for a in result["assignments"]}
    assert rooms[1] == rooms[2]
    assert result["disappointed"] == []


def test_students_without_a_room_are_explained():
    students = [S(1, 90), S(2, 80), S(3, 70)]
    result = allocate(students, [R(1)])
    assert len(result["assignments"]) == 2
    assert [u["student"] for u in result["unplaced"]] == [3]
    assert result["unplaced"][0]["reason"]


def test_lone_student_in_only_quad_is_reported_as_stranded():
    result = allocate([S(1)], [R(1, "quad")])
    assert [s["student"] for s in result["stranded"]] == [1]


def test_whole_plan_invariants():
    students, rooms = big_hostel()
    result = allocate(students, rooms)
    placed = [a["student"] for a in result["assignments"]]
    assert len(placed) == len(set(placed))
    assert len(placed) + len(result["unplaced"]) == len(students)
    stranded_rooms = {s["room"] for s in result["stranded"]}
    for r in result["rooms"]:
        assert r["filled"] <= r["capacity"]
        if r["capacity"] >= 3 and r["filled"] == 1:
            assert r["room"] in stranded_rooms
    assert result["unplaced"] == []
    assert result["stranded"] == []
    reasons = {d["student"]: d["reason"] for d in result["disappointed"]}
    assert reasons[9] == "not_mutual"
    assert reasons[7] == "not_mutual"
    assert 6 not in reasons                  # 6 asked for 7 and shares their room


def test_allocate_twice_gives_identical_output():
    students, rooms = big_hostel()
    first = json.dumps(allocate(students, rooms), sort_keys=True)
    second = json.dumps(allocate(students, rooms), sort_keys=True)
    shuffled = json.dumps(allocate(list(reversed(students)), list(reversed(rooms))),
                          sort_keys=True)
    assert first == second == shuffled


def test_progress_callback_is_monotonic_and_finishes():
    students, rooms = big_hostel()
    calls = []
    allocate(students, rooms, progress=lambda done, total, msg: calls.append((done, total)))
    dones = [c[0] for c in calls]
    assert dones == sorted(dones)
    assert {c[1] for c in calls} == {5}
    assert calls[-1] == (5, 5)
