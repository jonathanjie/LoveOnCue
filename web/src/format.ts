// Plain-language formatting. System words never reach the screen.
import {snap} from './state.js';
import type {Approval, Cue, Snapshot, Task} from './types.js';

export function clock(value: string | null): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-SG', {hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: snap().wedding.timezone}).format(new Date(value));
}

export function minutesBetween(from: string, to: string): number {
  return Math.round((new Date(to).getTime() - new Date(from).getTime()) / 60000);
}

/** "in 5 min", "5 min ago", "now". */
export function relative(value: string): string {
  const minutes = minutesBetween(snap().now, value);
  if (minutes === 0) return 'now';
  if (minutes > 0) return minutes < 90 ? `in ${minutes} min` : `at ${clock(value)}`;
  return -minutes < 90 ? `${-minutes} min ago` : `at ${clock(value)}`;
}

export function shift(minutes: number): string {
  return `${minutes > 0 ? '+' : '−'}${Math.abs(minutes)} min`;
}

export function teamName(id: string): string { return snap().teams.find(team => team.id === id)?.name || 'Another team'; }
export function memberName(id: string | null): string { return snap().members.find(member => member.id === id)?.name || 'A helper'; }
export function placeName(id: string | null): string { return snap().locations.find(place => place.id === id)?.name || 'No place set'; }
export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]?.toUpperCase() || '').join('');
}

const ROLE_WORDS: Record<string, string> = {
  coordinator: 'Coordinator', team_lead: 'Team lead', registration: 'Registration', usher: 'Usher',
  photographer: 'Photographer', family_liaison: 'Family liaison', banquet: 'Banquet', mc: 'MC', av: 'Sound & screens',
  transport: 'Transport', helper: 'Helper', couple: 'Couple',
};
export function roleWord(role: string): string { return ROLE_WORDS[role] || role.replaceAll('_', ' '); }
export const ROLES = Object.keys(ROLE_WORDS);

export type Tone = '' | 'urgent' | 'waiting' | 'done' | 'change';

export function jobStatus(task: Task): {label: string; tone: Tone} {
  if (task.state === 'done') return {label: 'Done', tone: 'done'};
  if (task.state === 'cancelled') return {label: 'Cancelled', tone: ''};
  if (task.overdue) return {label: 'Late', tone: 'urgent'};
  if (task.state === 'in_progress') return {label: 'Doing it', tone: 'done'};
  if (task.acknowledged_at) return {label: 'Got it', tone: 'done'};
  return {label: 'Not seen yet', tone: 'waiting'};
}

export function isOpenJob(task: Task): boolean { return task.state !== 'done' && task.state !== 'cancelled'; }

export function approvalStatus(approval: Approval, now: string): {label: string; tone: Tone; open: boolean} {
  if (approval.status === 'approved') return {label: 'Approved', tone: 'done', open: false};
  if (approval.status === 'rejected') return {label: 'Not approved', tone: '', open: false};
  if (approval.status === 'withdrawn') return {label: 'Withdrawn', tone: '', open: false};
  if (approval.status === 'superseded') return {label: 'Replaced', tone: '', open: false};
  if (approval.status !== 'pending') return {label: approval.status.replaceAll('_', ' '), tone: '', open: false};
  if (new Date(approval.expires_at) <= new Date(now)) return {label: 'Too late to decide', tone: '', open: false};
  return {label: 'Decide', tone: 'waiting', open: true};
}

export function openApprovals(s: Snapshot = snap()): Approval[] {
  return s.approvals.filter(approval => approvalStatus(approval, s.now).open);
}

/** The cue happening now, and the next one to start. */
export function nowAndNext(s: Snapshot = snap()): {now?: Cue; next?: Cue} {
  const live = s.timeline.filter(cue => cue.status === 'live');
  const upcoming = s.timeline.filter(cue => cue.status === 'scheduled');
  return {now: live[live.length - 1], next: upcoming[0]};
}

export function moved(cue: Cue): number { return minutesBetween(cue.planned_start, cue.current_start); }

/** The Telegram notice text tells people to tap a chat button; the app has its own button. */
export function noticeText(message: string): string {
  return message.split('\n\n').filter(part => !part.startsWith('Tap Acknowledge')).join('\n\n').trim();
}

const EVENT_WORDS: Record<string, string> = {
  task_action: 'Updated a job', arrival: 'Marked a guest as arrived', report_incident: 'Reported a problem',
  resolve_incident: 'Marked a problem as sorted', resolution_note: 'Added a note to a problem', propose_delay: 'Asked for a schedule change',
  decide_approval: 'Decided a schedule change', acknowledge_notification: 'Read an update', add_knowledge: 'Added a venue note',
  review_knowledge: 'Checked a venue note', revoke_member: 'Removed someone’s access', broadcast: 'Sent an update',
  set_wedding_status: 'Changed reminders', apply_guest_import: 'Imported guests', create_team: 'Added a team',
  create_member: 'Added a helper', edit_guest: 'Edited a guest', create_task: 'Added a job', create_location: 'Added a place',
  create_table: 'Added a table', create_timeline_item: 'Added a schedule cue', timeline_action: 'Marked a cue started or finished',
  create_vendor: 'Added a vendor', vendor_status: 'Updated a vendor', withdraw_report: 'Withdrew a report',
  report_withdrawn: 'Withdrew a report', set_deputy_enabled: 'Turned assistant check-ins on or off',
  deputy_enabled: 'Turned assistant check-ins on or off', deputy_quiet: 'Asked the assistant to stop check-ins',
  guest_details_access: 'Opened private guest details', family_contacts_access: 'Opened family contacts',
  incident_resolved_by_arrival: 'Closed a missing-person report on arrival', demo_seeded: 'Created the rehearsal wedding',
  notification_delivery: 'Delivered a message',
};
export function eventWords(type: string): string { return EVENT_WORDS[type] || type.replaceAll('_', ' '); }

/** "+08:00" for the wedding's time zone on the event date, for time inputs. */
export function zoneOffset(): string {
  const s = snap();
  const part = new Intl.DateTimeFormat('en-US', {timeZone: s.wedding.timezone, timeZoneName: 'longOffset'})
    .formatToParts(new Date(`${s.wedding.event_date}T12:00:00Z`))
    .find(piece => piece.type === 'timeZoneName')?.value || 'GMT';
  const offset = part.replace('GMT', '');
  return offset === '' ? '+00:00' : offset;
}

/** An ISO timestamp for a local time ("18:30") on the event date. */
export function eventTime(localTime: string): string {
  return `${snap().wedding.event_date}T${localTime}:00${zoneOffset()}`;
}
