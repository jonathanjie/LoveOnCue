// Review (coordinator): decide schedule changes with full context, and close problems.
import { command } from '../api.js';
import { can } from '../access.js';
import { approvalStatus, clock, memberName, relative, shift, teamName } from '../format.js';
import { rerender, snap, state } from '../state.js';
import { area, button, el, empty, list, note, pill, row, segmented, sheet, toast } from '../ui.js';
import { reportProblem } from './shared.js';
function proposer(approval) {
    if (!approval.proposed_by)
        return 'Someone on the team';
    const member = snap().members.find(item => item.id === approval.proposed_by);
    if (!member)
        return 'A helper';
    const team = member.team_ids[0];
    return team ? `${member.name} (${teamName(team)})` : member.name;
}
function openProblems() { return snap().incidents.filter(incident => incident.status === 'open'); }
export function reviewCount() {
    const s = snap();
    return s.approvals.filter(approval => approvalStatus(approval, s.now).open).length + openProblems().length;
}
export function review(main) {
    const s = snap();
    const pending = s.approvals.filter(approval => approvalStatus(approval, s.now).open);
    const problems = openProblems();
    main.append(segmented([
        { value: 'changes', label: 'Changes', count: pending.length },
        { value: 'problems', label: 'Problems', count: problems.length },
    ], state.reviewTab, value => { state.reviewTab = value; rerender(); }, 'What to review'));
    if (state.reviewTab === 'changes')
        changes(main);
    else
        problemList(main);
}
function changes(main) {
    const s = snap();
    const ordered = [...s.approvals].sort((a, b) => {
        const openA = approvalStatus(a, s.now).open, openB = approvalStatus(b, s.now).open;
        if (openA !== openB)
            return openA ? -1 : 1;
        return b.created_at.localeCompare(a.created_at);
    });
    if (!ordered.length) {
        main.append(empty('No schedule changes', 'When a team asks for more time, it shows here for you to decide.', 'clear'));
        return;
    }
    main.append(list(...ordered.map(approval => {
        const status = approvalStatus(approval, s.now);
        const meta = status.open
            ? `${proposer(approval)} · ${relative(approval.created_at)} · ${approval.changes.length} ${approval.changes.length === 1 ? 'cue moves' : 'cues move'}`
            : `${proposer(approval)} · ${clock(approval.decided_at || approval.created_at)}`;
        return row({ title: approval.title, meta, end: pill(status.label, status.tone), tone: status.open ? 'change' : '', onOpen: () => approvalSheet(approval) });
    })));
}
export function approvalSheet(approval) {
    const s = snap();
    const status = approvalStatus(approval, s.now);
    const stale = approval.base_timeline_version !== s.wedding.timeline_version;
    const diff = el('ul', 'diff');
    for (const change of approval.changes) {
        const cue = s.timeline.find(item => item.id === change.item_id);
        const limit = cue?.latest_end ? el('span', 'diff-shift', ` must end by ${clock(cue.latest_end)}`) : null;
        diff.append(el('li', 'diff-row', el('span', 'diff-title', change.title, limit), el('span', 'diff-times', el('s', '', clock(change.old_start)), el('strong', '', clock(change.new_start))), el('span', 'diff-shift', shift(change.delta_minutes))));
    }
    const affected = approval.affected_team_ids.map(teamName);
    const problems = [...approval.blockers];
    if (status.open && stale)
        problems.push('The schedule changed after this was asked. Ask the team to send it again.');
    const content = [
        el('div', 'quote', `“${approval.reason}”`, el('cite', '', `${proposer(approval)} · ${clock(approval.created_at)}`)),
        diff,
        ...problems.map(text => el('p', 'note error-text', text)),
        affected.length ? note(`${affected.join(', ')} will be told if you approve.`) : null,
        approval.decision_note ? note(`Your note: ${approval.decision_note}`) : null,
    ];
    const decidable = status.open && can('timeline:approve');
    const reason = area('Note to the team (optional)', '', 'Sent with your decision.');
    if (decidable)
        content.push(reason.wrap);
    sheet({
        eyebrow: status.open ? `Schedule change · decide by ${clock(approval.expires_at)}` : `Schedule change · ${status.label}`,
        eyebrowTone: 'change', title: approval.title, content,
        actions: close => {
            if (!decidable)
                return [button('Close', close)];
            const decide = (decision, message) => async () => {
                await command({ type: 'decide_approval', approval_id: approval.id, decision, note: reason.input.value.trim() });
                close();
                toast(message);
            };
            const approve = button('Approve', decide('approve', 'Approved. The schedule is updated and the teams are told.'), 'primary');
            approve.disabled = stale || approval.blockers.length > 0;
            return [button('Not approved', decide('reject', `Not approved. ${memberName(approval.proposed_by)} is told.`)), approve];
        },
    });
}
function problemList(main) {
    const all = [...snap().incidents].sort((a, b) => {
        if (a.status !== b.status)
            return a.status === 'open' ? -1 : 1;
        if (a.severity !== b.severity)
            return a.severity === 'urgent' ? -1 : 1;
        return b.created_at.localeCompare(a.created_at);
    });
    if (!all.length)
        main.append(empty('No problems reported', 'Problems reported in chat or here show up in this list.', 'clear'));
    else
        main.append(list(...all.map(incident => row({
            title: incident.title,
            meta: `${memberName(incident.reported_by)} · ${relative(incident.created_at)}`,
            end: incident.status !== 'open' ? pill('Sorted', 'done') : incident.severity === 'urgent' ? pill('Urgent', 'urgent') : pill('Open', 'waiting'),
            tone: incident.status === 'open' ? (incident.severity === 'urgent' ? 'urgent' : 'waiting') : '',
            onOpen: () => problemSheet(incident),
        }))));
    if (can('incidents:report'))
        main.append(el('div', 'group', button('Report a problem', reportProblem, 'wide')));
}
export function problemSheet(incident) {
    const open = incident.status === 'open';
    const resolvable = open && can('incidents:resolve');
    const resolution = area('How was it sorted?', '', 'Saved with the problem for the activity log.');
    sheet({
        eyebrow: `${incident.severity === 'urgent' ? 'Urgent problem' : 'Problem'} · ${open ? 'open' : 'sorted'}`,
        eyebrowTone: incident.severity === 'urgent' ? 'urgent' : '',
        title: incident.title,
        content: [el('p', 'card-body', incident.details), note(`Reported by ${memberName(incident.reported_by)} at ${clock(incident.created_at)}`), resolvable ? resolution.wrap : null],
        actions: close => resolvable ? [
            button('Close', close),
            button('Mark as sorted', async () => {
                if (!resolution.input.value.trim())
                    throw new Error('Write one line about how it was sorted.');
                await command({ type: 'resolve_incident', incident_id: incident.id, note: resolution.input.value.trim() });
                close();
                toast('Marked as sorted.');
            }, 'primary'),
        ] : [button('Close', close)],
    });
}
