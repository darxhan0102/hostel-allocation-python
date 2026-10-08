"""Pure room-allocation logic. No database, no HTTP.

Students name a room type, a floor, and up to two people they would like to
live with. This module turns that pile of wishes into a seating plan.

The rules, stated once so they can be defended
----------------------------------------------
1. **Only MUTUAL requests count.** If Ishita asks for Janvi but Janvi asks for
   Kabir, Ishita gets nothing from that request. A one-way request is a crush,
   not an agreement, and honouring it would mean putting somebody in a room
   with a person who did not choose them.

2. **Rank decides every tie, and rank is fixed before any allocation starts.**
   `merit_key` is (merit descending, year descending, id ascending). It never
   consults the clock, a random number, or the order rows came out of a
   database, so the same input always produces the same plan - which is the
   only reason a student can be told *why* they lost.

3. **A group may not exceed the largest room.** Four mutually-agreed friends
   fit a quad. Five do not. The group is grown outward from its highest-ranked
   member, best-ranked neighbour first, until the room is full; whoever is
   still outside when the door closes is recorded as `outranked`, with the
   name of the person who beat them.

4. **Nobody is left alone in a four-bed room.** A single occupant in a quad is
   both miserable and a waste of three beds, so `is_viable_occupancy` forbids
   it and `allocate` runs a repair pass: first try to move that person
   somewhere smaller, and failing that bring somebody in to join them.

THE HARD PART, in one sentence: A requests B, B requests C. Somebody has to be
disappointed. Rule 1 decides whether anyone is paired at all, and rule 2
decides who keeps B when both A and C want them. Every disappointment comes
back with a reason, because "the algorithm said so" is not an answer you can
give to a nineteen-year-old.

What to test
------------
* ``merit_key`` / ``rank_students`` - equal merit falls through to year, equal
  year falls through to id. The ordering must be total: no ties ever survive.
* ``mutual_pairs`` - one-way requests produce nothing; a self-request produces
  nothing; A->B and B->A produce exactly ONE pair, not two.
* ``one_way_requests`` - the A->B->C chain. Ishita must appear with reason
  ``not_mutual``.
* ``form_groups`` - a mutual pair, a mutual triple, a chain, and a mutual
  component of FIVE that must split 4 + 1 with the right person bumped.
  Check the bumped student's ``blocked_by``.
* ``is_viable_occupancy`` - 1 in a quad is False, 1 in a single is True, 1 in a
  double is True, 0 in anything is True (an empty room is fine).
* ``_repair_lonely`` - both strategies. Give it a hostel where the only fix is
  to move somebody IN, and one where neither fix exists so ``stranded`` fires.
* ``room_score`` - type match beats floor match; a tight fit beats a loose one;
  a lone student must not score an empty quad highest.
* ``allocate`` - a one-way request that the allocation SATISFIED anyway must
  not be reported as a disappointment. Harsh asks for Lakshmi, Lakshmi never
  asks for Harsh, but the group built around their mutual friends puts them in
  the same quad - Harsh got what he wanted and must not appear in the list.
* ``allocate`` - the whole plan. Every student is either placed or explained.
  No room over capacity. No lonely quad. Running it twice on the same input
  must give byte-identical output.
* ``allocate`` with ``progress`` - the callback must fire, must be monotonic,
  and must reach total == done.
"""

ROOM_CAPACITY = {"single": 1, "double": 2, "triple": 3, "quad": 4}
MAX_ROOMMATE_REQUESTS = 2
LONELY_FROM_CAPACITY = 3      # a room this size or bigger must not hold just one


class AllocationError(ValueError):
    pass


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------

def merit_key(student):
    """The one true ordering. Lower sorts first, i.e. gets picked first.

    Merit first, then seniority, then id. The id tiebreak is not decoration -
    without it two students with identical merit and year would be ordered by
    whatever the database felt like, and the allocation would stop being
    reproducible.
    """
    return (-float(student.get("merit", 0)),
            -int(student.get("year", 0)),
            int(student["id"]))


def rank_students(students):
    """Return a new list in allocation order, each student given a `rank`."""
    ordered = sorted(students, key=merit_key)
    return [{**s, "rank": i + 1} for i, s in enumerate(ordered)]


# --------------------------------------------------------------------------
# Who actually agreed with whom
# --------------------------------------------------------------------------

def _wanted(student):
    out = []
    for w in (student.get("wants") or []):
        w = int(w)
        if w != int(student["id"]) and w not in out:
            out.append(w)
    return out[:MAX_ROOMMATE_REQUESTS]


def mutual_pairs(students):
    """Every pair where BOTH sides asked for the other.

    Returned as a sorted list of (lower_id, higher_id) tuples so the result is
    stable and comparable in a test.
    """
    wants = {int(s["id"]): set(_wanted(s)) for s in students}
    pairs = set()
    for sid, picks in wants.items():
        for other in picks:
            if other in wants and sid in wants[other]:
                pairs.add((min(sid, other), max(sid, other)))
    return sorted(pairs)


def one_way_requests(students):
    """Requests that were never returned - the first kind of disappointment.

    This is the A -> B -> C chain showing up as data: A asked for B, B asked
    for C, so A appears here and B appears here, and only B and C are paired.
    """
    wants = {int(s["id"]): set(_wanted(s)) for s in students}
    names = {int(s["id"]): s.get("name", str(s["id"])) for s in students}
    out = []
    for sid in sorted(wants):
        for other in sorted(wants[sid]):
            if other not in wants:
                out.append({"student": sid, "name": names[sid], "wanted": other,
                            "wanted_name": None, "reason": "no_such_student"})
            elif sid not in wants[other]:
                out.append({"student": sid, "name": names[sid], "wanted": other,
                            "wanted_name": names.get(other),
                            "reason": "not_mutual"})
    return out


def adjacency(students):
    """Undirected graph of mutual agreements only."""
    adj = {int(s["id"]): set() for s in students}
    for a, b in mutual_pairs(students):
        adj[a].add(b)
        adj[b].add(a)
    return adj


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------

def form_groups(ranked, max_size=4):
    """Turn the mutual graph into groups no larger than the largest room.

    Returns (groups, bumped).
      groups : [[student_id, ...], ...] - best-ranked member first
      bumped : [{"student":id, "blocked_by":id, "reason":"outranked"}, ...]

    A group is grown outward from the highest-ranked unplaced student, taking
    the best-ranked mutual neighbour available at each step. When the room is
    full, anybody still reaching for a member of that group is bumped - and we
    record exactly who beat them, because that is the sentence the warden has
    to read out.
    """
    if max_size < 1:
        raise AllocationError("the largest room must hold at least one person")
    adj = adjacency(ranked)
    order = [int(s["id"]) for s in ranked]
    pos = {sid: i for i, sid in enumerate(order)}
    placed, groups, bumped = set(), [], []

    for seed in order:
        if seed in placed:
            continue
        group = [seed]
        placed.add(seed)
        frontier = sorted(adj[seed] - placed, key=lambda x: pos[x])
        while frontier and len(group) < max_size:
            nxt = frontier.pop(0)
            if nxt in placed:
                continue
            group.append(nxt)
            placed.add(nxt)
            frontier = sorted((set(frontier) | adj[nxt]) - placed, key=lambda x: pos[x])
        # Whoever is still outside wanted in and could not fit.
        for left in frontier:
            if left in placed:
                continue
            winners = sorted((m for m in group if left in adj[m]), key=lambda x: pos[x])
            bumped.append({"student": left,
                           "blocked_by": winners[0] if winners else group[0],
                           "group": list(group),
                           "reason": "outranked"})
        groups.append(group)
    return groups, bumped


# --------------------------------------------------------------------------
# Rooms
# --------------------------------------------------------------------------

def capacity_of(room):
    if room.get("capacity"):
        return int(room["capacity"])
    kind = str(room.get("room_type", "")).lower()
    if kind not in ROOM_CAPACITY:
        raise AllocationError(f"unknown room type {room.get('room_type')!r}")
    return ROOM_CAPACITY[kind]


def is_viable_occupancy(capacity, filled):
    """Is it acceptable to leave a room in this state?

    One student alone in a quad is three empty beds and a long year. An empty
    room is fine - nobody is suffering in it.
    """
    cap, n = int(capacity), int(filled)
    if n > cap:
        return False
    # One student alone in a room built for three or more.
    return not (n == 1 and cap >= LONELY_FROM_CAPACITY)


def room_score(room, group_size, leader, occupied=0):
    """How good is this room for this group? Higher is better.

    Nothing here is subtle. It just has to be explainable:
      * the room type the leader asked for is worth more than the floor
      * a tight fit beats rattling around, so empty beds cost a point each
      * topping up a part-full room beats opening a fresh one
      * dumping one student into an empty quad is heavily penalised, which is
        how rule 4 is enforced during placement rather than only afterwards
    """
    cap = capacity_of(room)
    free = cap - int(occupied)
    if free < group_size:
        return None
    pts = 0
    if str(room.get("room_type", "")).lower() == str(leader.get("room_type", "")).lower():
        pts += 5
    if leader.get("floor_pref") is not None and int(room.get("floor", -1)) == int(leader["floor_pref"]):
        pts += 3
    pts -= (free - group_size)
    if occupied:
        pts += 1
    if not is_viable_occupancy(cap, int(occupied) + group_size):
        pts -= 10
    return pts


def choose_room(rooms_state, group_size, leader):
    """Pick the best available room. Ties break on room id, never on luck."""
    best, best_pts = None, None
    for r in rooms_state:
        pts = room_score(r, group_size, leader, len(r["occupants"]))
        if pts is None:
            continue
        if best_pts is None or pts > best_pts or (pts == best_pts and r["id"] < best["id"]):
            best, best_pts = r, pts
    return best


# --------------------------------------------------------------------------
# The whole plan
# --------------------------------------------------------------------------

def _fresh_state(rooms):
    return [{"id": int(r["id"]), "code": r.get("code", str(r["id"])),
             "block": r.get("block", ""), "floor": int(r.get("floor", 0)),
             "room_type": str(r.get("room_type", "")).lower(),
             "capacity": capacity_of(r), "occupants": []}
            for r in sorted(rooms, key=lambda r: int(r["id"]))]


def _repair_lonely(state, pos=None):
    """Second pass: nobody alone in a room built for three or more.

    Two strategies, tried in this order:

    1. **Move them out.** Put the lone student in the smallest room that can
       take them without creating the same problem somewhere else.
    2. **Bring somebody in.** If every smaller room is full, move one student
       INTO the big room for company. The donor is taken from the room with
       the fewest occupants - moving a solo student disturbs nobody, whereas
       pulling someone out of an agreed pair would break a promise to fix a
       preference - and among equals the lowest-ranked moves, because rank
       decides everything else in this module too.

    If neither works - the hostel is a row of quads and there are seven
    students - the student stays put and the plan SAYS so in `stranded`,
    rather than quietly pretending the rule was honoured.
    """
    pos = pos or {}
    moved, stranded = [], []
    for room in state:
        if is_viable_occupancy(room["capacity"], len(room["occupants"])):
            continue
        lone = room["occupants"][0]

        targets = [r for r in state
                   if r["id"] != room["id"]
                   and len(r["occupants"]) < r["capacity"]
                   and is_viable_occupancy(r["capacity"], len(r["occupants"]) + 1)]
        targets.sort(key=lambda r: (r["capacity"], -len(r["occupants"]), r["id"]))
        if targets:
            room["occupants"].remove(lone)
            targets[0]["occupants"].append(lone)
            moved.append({"student": lone, "from": room["code"], "to": targets[0]["code"],
                          "reason": "would have been alone in a "
                                    f"{room['capacity']}-bed room"})
            continue

        donors = []
        for r in state:
            if r["id"] == room["id"] or not r["occupants"]:
                continue
            if not is_viable_occupancy(r["capacity"], len(r["occupants"]) - 1):
                continue
            for occupant in r["occupants"]:
                donors.append((len(r["occupants"]), -pos.get(occupant, 0), r["id"],
                               occupant, r))
        donors.sort(key=lambda d: (d[0], d[1], d[2], d[3]))
        if donors:
            _, _, _, who, src = donors[0]
            src["occupants"].remove(who)
            room["occupants"].append(who)
            moved.append({"student": who, "from": src["code"], "to": room["code"],
                          "reason": f"moved in for company so nobody was alone in a "
                                    f"{room['capacity']}-bed room"})
        else:
            stranded.append({"student": lone, "room": room["code"],
                             "reason": "alone in a "
                                       f"{room['capacity']}-bed room, nowhere to move them"})
    return moved, stranded


def allocate(students, rooms, progress=None):
    """Produce a full allocation.

    `progress` is an optional callable (done, total, message). It is the only
    concession this module makes to the outside world, and it is a plain
    function - the caller decides whether that means writing to Redis,
    printing, or nothing at all. The module itself stays pure.
    """
    if not students:
        raise AllocationError("there are no students to allocate")
    if not rooms:
        raise AllocationError("there are no rooms to allocate")

    def tick(done, total, msg):
        if progress:
            progress(done, total, msg)

    ranked = rank_students(students)
    by_id = {int(s["id"]): s for s in ranked}
    state = _fresh_state(rooms)
    biggest = max(r["capacity"] for r in state)

    tick(1, 5, f"ranked {len(ranked)} students")
    groups, bumped = form_groups(ranked, biggest)
    tick(2, 5, f"formed {len(groups)} groups from mutual requests")

    # Groups go in order of their best member, which is also the order the
    # students would expect: the top of the merit list picks first.
    groups.sort(key=lambda g: min(by_id[m]["rank"] for m in g))

    placements, unplaced = {}, []
    total = len(groups)
    for i, group in enumerate(groups, start=1):
        leader = by_id[group[0]]
        room = choose_room(state, len(group), leader)
        if room is None:
            for m in group:
                unplaced.append({"student": m, "name": by_id[m].get("name"),
                                 "reason": "no room large enough was free"})
        else:
            room["occupants"].extend(group)
            for m in group:
                placements[m] = room["id"]
        if total and (i % 10 == 0 or i == total):
            tick(3, 5, f"placed {i} of {total} groups")

    moved, stranded = _repair_lonely(state, {int(s["id"]): s["rank"] for s in ranked})
    for r in state:
        for m in r["occupants"]:
            placements[m] = r["id"]
    tick(4, 5, f"repaired {len(moved)} lonely rooms")

    rooms_by_id = {r["id"]: r for r in state}
    assignments = []
    for s in ranked:
        sid = int(s["id"])
        rid = placements.get(sid)
        if rid is None:
            continue
        room = rooms_by_id[rid]
        mates = [by_id[o].get("name") for o in room["occupants"] if o != sid]
        assignments.append({
            "student": sid, "name": s.get("name"), "rank": s["rank"],
            "merit": float(s.get("merit", 0)), "year": int(s.get("year", 0)),
            "room": room["code"], "room_id": room["id"],
            "room_type": room["room_type"], "floor": room["floor"],
            "got_room_type": room["room_type"] == str(s.get("room_type", "")).lower(),
            "got_floor": s.get("floor_pref") is not None and room["floor"] == int(s["floor_pref"]),
            "roommates": sorted(m for m in mates if m),
        })

    def _ended_up_together(a, b):
        """Did these two get the same room in the end?

        A one-way request can still be satisfied: Harsh asks for Lakshmi,
        Lakshmi never asks for Harsh, but the group grown around their mutual
        friends puts them in the same quad anyway. Reporting Harsh as
        disappointed when he is living with the person he asked for is simply
        wrong, and it is the quickest way to lose a student's trust in the
        whole plan.
        """
        if a is None or b is None:
            return False
        here, there = placements.get(int(a)), placements.get(int(b))
        return here is not None and here == there

    disappointed = [d for d in one_way_requests(ranked)
                    if not _ended_up_together(d["student"], d.get("wanted"))]
    for b in bumped:
        if _ended_up_together(b["student"], b["blocked_by"]):
            continue
        disappointed.append({
            "student": b["student"], "name": by_id[b["student"]].get("name"),
            "wanted": b["blocked_by"], "wanted_name": by_id[b["blocked_by"]].get("name"),
            "reason": "outranked",
            "detail": (f"{by_id[b['blocked_by']].get('name')}'s room filled up with "
                       f"students ranked above you")})

    tick(5, 5, "done")
    return {
        "assignments": assignments,
        "rooms": [{"room": r["code"], "room_type": r["room_type"], "floor": r["floor"],
                   "capacity": r["capacity"], "filled": len(r["occupants"]),
                   "occupants": sorted(by_id[o].get("name") for o in r["occupants"])}
                  for r in state if r["occupants"]],
        "unplaced": unplaced,
        "disappointed": disappointed,
        "moved_to_avoid_lonely_room": moved,
        "stranded": stranded,
        "summary": {
            "students": len(ranked),
            "placed": len(assignments),
            "groups": len(groups),
            "mutual_pairs": len(mutual_pairs(ranked)),
            "got_room_type": sum(1 for a in assignments if a["got_room_type"]),
            "got_floor": sum(1 for a in assignments if a["got_floor"]),
            "rooms_used": sum(1 for r in state if r["occupants"]),
        },
    }
