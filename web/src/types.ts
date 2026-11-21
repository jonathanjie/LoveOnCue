// Shapes returned by the LoveOnCue API. The server is the authority; these only describe it.

export type Dict = Record<string, unknown>;

export type Member = {id: string; name: string; roles: string[]; team_ids: string[]; active: boolean; telegram_linked: boolean | null};
export type Task = {
  id: string; title: string; instructions: string; owner_id: string; team_id: string; location_id: string;
  due_at: string; planned_due: string; state: string; version: number; acknowledged_at: string | null;
  completed_at: string | null; blocked_by: string[]; overdue: boolean; mine: boolean; can_edit: boolean;
};
export type Cue = {
  id: string; title: string; planned_start: string; current_start: string; duration_minutes: number;
  location_id: string; team_ids: string[]; status: string; instructions: string; latest_end: string | null;
  actual_start: string | null; actual_end: string | null;
};
export type Change = {item_id: string; title: string; old_start: string; new_start: string; delta_minutes: number; team_ids: string[]};
export type Approval = {
  id: string; title: string; reason: string; status: string; proposed_by: string | null; base_timeline_version: number;
  changes: Change[]; blockers: string[]; affected_team_ids: string[]; created_at: string; expires_at: string;
  decided_by: string | null; decided_at: string | null; decision_note: string | null;
};
export type Notice = {id: string; topic: string; message: string; state: string; created_at: string; acknowledged_at: string | null; attempts: number; last_error: string | null};
export type Incident = {id: string; title: string; details: string; severity: string; kind: string; status: string; created_at: string; reported_by: string | null};
export type Knowledge = {id: string; title: string; source_name: string; revision: number; status: string; verified_at: string | null; text: string | null; audience_team_ids: string[]};
export type Guest = {id: string; name: string; table: string | null; location_id: string | null; attendance: string; rsvp: string; version: number; dietary?: string | null};
export type GuestDetails = {id: string; name: string; table_id: string | null; rsvp: string; relationship: string | null; dietary: string | null; private_phone: string | null; version: number};
export type Vendor = {id: string; name: string; category: string; status: string; contact_name: string; contact_phone: string; team_id: string; expected_at: string};
export type Place = {id: string; name: string; directions: string; x: number; y: number};
export type Table = {id: string; label: string; location_id: string; capacity: number; x: number; y: number};
export type Team = {id: string; name: string};

export type Snapshot = {
  wedding: {id: string; name: string; timezone: string; event_date: string; venue: string; status: string; state_version: number; timeline_version: number};
  now: string;
  me: {id: string; name: string; roles: string[]; team_ids: string[]; grants: string[]};
  teams: Team[]; members: Member[]; locations: Place[]; tables: Table[]; tasks: Task[]; timeline: Cue[];
  incidents: Incident[]; approvals: Approval[]; notifications: Notice[]; knowledge: Knowledge[]; vendors: Vendor[];
  counts: {guests: number; onsite: number; open_incidents: number; pending_approvals: number};
};

export type LatestUpdate = {kind: string; message: string; sent_at: string; total: number; read: {name: string; at: string}[]; not_read: string[]};
export type Brief = {
  urgent: {title: string; detail: string}[]; followups: {title: string; detail: string}[];
  notes: {title: string; detail: string}[]; latest_update: LatestUpdate | null;
};

export type Config = {demo: boolean; demo_members: Member[]; agent_mode: string; telegram_configured: boolean; notifications_live: boolean};
export type ImportPreview = {id: string; count: number; errors: string[]; error_count: number; sample: {name: string; table_id: string; rsvp: string}[]};
export type AuditEntry = {id: string; actor_id: string; event_type: string; entity_id: string; detail: unknown; created_at: string};
export type Reference = {title: string; source: string; revision: number; line: number; excerpt: string};
