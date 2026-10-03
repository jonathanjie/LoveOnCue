"""Bounded CSV preview. No import takes effect until the coordinator confirms it."""
from __future__ import annotations

import csv
import io
from collections import Counter

from .clock import Clock
from .db import Database
from .errors import OpsError
from .models import GuestImport, Person, SeatingTable, new_id
from .operations import audit
from .policy import Actor, load_access, require_human
from .views import rows


class Imports:
    def __init__(self, db: Database, wid: str, clock: Clock):
        self.db, self.wid, self.clock = db, wid, clock

    def preview(self, actor: Actor, text: str) -> dict:
        require_human(actor)
        if len(text.encode()) > 200_000:
            raise OpsError("too_large", "CSV exceeds 200 KB", 413)
        try:
            reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or set(reader.fieldnames) - {"name", "table", "rsvp", "dietary"} or not {"name", "table"}.issubset(reader.fieldnames):
                raise OpsError("invalid_csv", "CSV needs unique name,table columns; optional rsvp,dietary")
            entries = []
            for entry in reader:
                if len(entries) >= 500:
                    raise OpsError("too_large", "At most 500 guests per import", 413)
                if None in entry or any(v is None for v in entry.values()):
                    raise OpsError("invalid_csv", "A CSV row has an incorrect column count")
                entries.append(entry)
        except csv.Error as exc:
            raise OpsError("invalid_csv", "Malformed CSV") from exc
        with self.db.transaction(self.wid, write=True) as (s, w):
            load_access(s, actor, self.wid).require("guests:manage")
            if w.status == "archived":
                raise OpsError("archived", "This wedding is read-only", 409)
            tables = {t.label: t for t in rows(s, SeatingTable, self.wid)}
            people = rows(s, Person, self.wid)
            occupied = Counter(p.table_id for p in people if p.is_guest and p.rsvp != "no")
            names = {p.name.casefold() for p in people}
            errors, normalized = [], []
            for number, entry in enumerate(entries, 2):
                name = entry["name"].strip()
                table = tables.get(entry["table"].strip())
                rsvp = entry.get("rsvp", "yes").strip() or "yes"
                diet = entry.get("dietary", "").strip()
                if not 2 <= len(name) <= 120:
                    errors.append(f"Row {number}: name must contain 2–120 characters")
                if name.casefold() in names:
                    errors.append(f"Row {number}: duplicate name; resolve manually before import")
                names.add(name.casefold())
                if table is None:
                    errors.append(f"Row {number}: table does not exist")
                if rsvp not in {"yes", "no", "unknown"}:
                    errors.append(f"Row {number}: invalid RSVP")
                if len(diet) > 300:
                    errors.append(f"Row {number}: dietary note exceeds 300 characters")
                if table and rsvp != "no":
                    occupied[table.id] += 1
                normalized.append({"name": name, "table_id": table.id if table else None, "rsvp": rsvp, "dietary": diet})
            for table in tables.values():
                if occupied[table.id] > table.capacity:
                    errors.append(f"Table {table.label}: {occupied[table.id]} seats assigned; capacity {table.capacity}")
            if not normalized:
                errors.append("The CSV contains no guests")
            preview = {"count": len(normalized), "errors": errors[:100], "error_count": len(errors),
                       "sample": [{"name": x["name"], "table_id": x["table_id"], "rsvp": x["rsvp"]} for x in normalized[:10]]}
            batch = GuestImport(id=new_id(), wedding_id=self.wid, created_by=actor.member_id,
                                rows=normalized, preview=preview, base_state_version=w.state_version, created_at=self.clock.now())
            s.add(batch)
            audit(s, w, actor.member_id, "guest_import_preview", batch.id,
                  {"count": len(normalized), "error_count": len(errors)}, self.clock.now())
            return {"id": batch.id, **preview}

    def export_guests(self, actor: Actor) -> str:
        def safe(value: str | None) -> str:
            text = value or ""
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text
        with self.db.transaction(self.wid, write=True) as (s, w):
            load_access(s, actor, self.wid).require("guests:manage")
            tables = {t.id: t.label for t in rows(s, SeatingTable, self.wid)}
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["name", "table", "rsvp", "attendance"])
            for person in rows(s, Person, self.wid):
                if person.is_guest:
                    writer.writerow([safe(person.name), safe(tables.get(person.table_id)), person.rsvp, person.attendance])
            audit(s, w, actor.member_id, "guest_export", self.wid, {"private_fields_excluded": True}, self.clock.now())
            return output.getvalue()
