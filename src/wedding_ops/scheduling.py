"""Pure forward propagation. Keeps slack; never shortens an activity or spends money."""
from __future__ import annotations

from datetime import timedelta

from .clock import iso
from .errors import OpsError, conflict, missing
from .models import TimelineDependency, TimelineItem


def propose_shift(items: list[TimelineItem], edges: list[TimelineDependency], item_id: str, minutes: int) -> dict:
    by_id = {item.id: item for item in items}
    if item_id not in by_id:
        raise missing()
    if by_id[item_id].status != "scheduled":
        raise conflict("Only a not-yet-started timeline item can be delayed")
    children: dict[str, list[TimelineDependency]] = {i: [] for i in by_id}
    indegree = dict.fromkeys(by_id, 0)
    for edge in edges:
        if edge.item_id not in by_id or edge.depends_on_id not in by_id:
            raise conflict("The timeline contains an invalid dependency")
        children[edge.depends_on_id].append(edge)
        indegree[edge.item_id] += 1
    ready = sorted(i for i, count in indegree.items() if count == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for edge in children[node]:
            indegree[edge.item_id] -= 1
            if indegree[edge.item_id] == 0:
                ready.append(edge.item_id)
    if len(order) != len(items):
        raise OpsError("dependency_cycle", "Timeline dependency cycle: fix the run sheet before proposing changes", 409)
    starts = {i.id: i.current_start for i in items}
    starts[item_id] += timedelta(minutes=minutes)
    affected = {item_id}
    blockers: list[str] = []
    for parent in order:
        if parent not in affected:
            continue
        for edge in children[parent]:
            earliest = starts[parent] + timedelta(minutes=by_id[parent].duration_minutes + edge.lag_minutes)
            if starts[edge.item_id] < earliest:
                starts[edge.item_id] = earliest
                affected.add(edge.item_id)
    changes = []
    teams: set[str] = set()
    for ident in order:
        item = by_id[ident]
        if starts[ident] == item.current_start:
            continue
        end = starts[ident] + timedelta(minutes=item.duration_minutes)
        if item.status != "scheduled":
            blockers.append(f"{item.title}: already {item.status}")
        if item.latest_end and end > item.latest_end:
            blockers.append(f"{item.title}: would exceed its hard latest-end constraint")
        teams.update(item.team_ids)
        changes.append({"item_id": ident, "title": item.title, "old_start": iso(item.current_start),
                        "new_start": iso(starts[ident]), "delta_minutes": int((starts[ident] - item.current_start).total_seconds() / 60),
                        "team_ids": item.team_ids})
    return {"changes": changes, "affected_team_ids": sorted(teams), "blockers": blockers}
