// Crew (coordinator): who has seen their next job, who read the latest update, and sending updates.
import { api, command } from '../api.js';
import { can } from '../access.js';
import { clock, initials, isOpenJob, jobStatus, memberName, placeName, roleWord, teamName } from '../format.js';
import { go, rerender, snap, state } from '../state.js';
import { area, button, chips, el, empty, field, list, note, pill, row, segmented, sheet, toast } from '../ui.js';
/** Each active helper with their next open job. "Seen" means they acknowledged it. */
export function crewEntries() {
    const s = snap();
    return s.members
        .filter(member => member.active && !member.roles.includes('coordinator') && !member.roles.includes('couple'))
        .map(member => {
        const next = s.tasks.filter(task => task.owner_id === member.id && isOpenJob(task))
            .sort((a, b) => a.due_at.localeCompare(b.due_at))[0];
        return { member, next, seen: !next || Boolean(next.acknowledged_at) };
    });
}
export function notSeen(entries = crewEntries()) { return entries.filter(entry => entry.next && !entry.seen); }
function entryRow(entry) {
    const { member, next } = entry;
    // Not being on Telegram comes first: those people cannot be reminded in chat.
    const offTelegram = member.telegram_linked === false ? 'No Telegram · ' : '';
    const meta = next ? `${offTelegram}${clock(next.due_at)} ${next.title}` : `${offTelegram}${member.roles.map(roleWord).join(', ')} · no open job`;
    let end;
    if (!next)
        end = pill('Free');
    else if (next.overdue && !next.acknowledged_at)
        end = pill('Late', 'urgent');
    else if (!next.acknowledged_at)
        end = pill('Not seen', 'waiting');
    else
        end = pill(`Seen ${clock(next.acknowledged_at)}`, 'done');
    return row({ title: member.name, meta, end, lead: el('span', 'avatar', initials(member.name)), onOpen: () => personSheet(member) });
}
export function crew(main) {
    const entries = crewEntries();
    const missing = notSeen(entries);
    const withJobs = entries.filter(entry => entry.next);
    const update = state.brief?.latest_update;
    const stats = el('div', 'stats', el('div', `stat${missing.length ? ' is-alert' : ''}`, el('div', 'stat-value', String(missing.length), el('small', '', ` /${withJobs.length}`)), el('div', 'stat-label', 'Not seen job')), readStat());
    if (can('messages:broadcast')) {
        const send = el('button', 'stat is-action', el('div', 'stat-value', '+'), el('div', 'stat-label', 'Send update'));
        send.type = 'button';
        send.addEventListener('click', sendUpdate);
        stats.append(send);
    }
    main.append(stats);
    const got = entries.filter(entry => entry.next && entry.seen);
    main.append(el('div', 'group', segmented([
        { value: 'not_seen', label: 'Not seen', count: missing.length },
        { value: 'got_it', label: 'Got it', count: got.length },
        { value: 'everyone', label: 'Everyone' },
    ], state.crewTab, value => { state.crewTab = value; rerender(); }, 'Which people')));
    const shown = state.crewTab === 'not_seen' ? missing : state.crewTab === 'got_it' ? got : entries;
    if (state.crewTab === 'everyone') {
        const people = snap().members.filter(member => member.id !== snap().me.id);
        main.append(list(...people.map(member => {
            const entry = entries.find(item => item.member.id === member.id);
            if (entry)
                return entryRow(entry);
            return row({ title: member.name, meta: member.roles.map(roleWord).join(', '), lead: el('span', 'avatar', initials(member.name)),
                end: member.active ? null : pill('No access', 'urgent'), onOpen: () => personSheet(member) });
        })));
    }
    else if (!shown.length) {
        main.append(empty(state.crewTab === 'not_seen' ? 'Everyone has seen their next job' : 'Nobody has confirmed yet', '', state.crewTab === 'not_seen' ? 'clear' : undefined));
    }
    else {
        main.append(list(...shown.map(entryRow)));
    }
    if (update && update.not_read.length) {
        main.append(note(`Last update, ${clock(update.sent_at)}. Not read yet: ${update.not_read.join(', ')}.`));
    }
}
function readStat() {
    const update = state.brief?.latest_update;
    const node = el('button', 'stat', el('div', 'stat-value', update ? String(update.read.length) : '–', update ? el('small', '', ` /${update.total}`) : null), el('div', 'stat-label', 'Read update'));
    node.type = 'button';
    node.disabled = !update;
    node.addEventListener('click', () => { if (update)
        updateSheet(); });
    return node;
}
function updateSheet() {
    const update = state.brief?.latest_update;
    if (!update)
        return;
    sheet({
        eyebrow: `Latest ${update.kind} · ${clock(update.sent_at)}`, title: `${update.read.length} of ${update.total} have read it`,
        content: [
            el('div', 'quote', update.message),
            el('div', 'group', el('h3', 'group-title', 'Not read yet'), update.not_read.length ? list(...update.not_read.map(name => row({ title: name }))) : note('Everyone has read it.')),
            update.read.length ? el('div', 'group', el('h3', 'group-title', 'Read'), list(...update.read.map(entry => row({ title: entry.name, end: pill(clock(entry.at), 'done') })))) : null,
        ],
    });
}
/** Send an update to chosen teams. Uses the existing broadcast command. */
export function sendUpdate() {
    const s = snap();
    const teams = chips('Who should get it?', s.teams.map(team => ({ id: team.id, name: team.name })), true);
    const everyone = el('button', 'button quiet small', 'Choose every team');
    everyone.type = 'button';
    everyone.addEventListener('click', () => {
        for (const input of Array.from(teams.wrap.querySelectorAll('input')))
            input.checked = true;
    });
    const message = area('Message', '', 'Say what changed and what people should do.');
    sheet({
        eyebrow: 'Send an update', title: 'Tell the teams',
        text: 'Each person gets it in Telegram with a button to say they have read it.',
        content: [teams.wrap, everyone, message.wrap],
        actions: close => [
            button('Cancel', close),
            button('Send update', async () => {
                const chosen = teams.values();
                if (!chosen.length)
                    throw new Error('Choose at least one team.');
                if (message.input.value.trim().length < 1)
                    throw new Error('Write the message first.');
                await command({ type: 'broadcast', team_ids: chosen, message: message.input.value.trim() });
                close();
                toast(`Sent to ${chosen.length === s.teams.length ? 'every team' : chosen.map(teamName).join(', ')}.`);
            }, 'primary'),
        ],
    });
}
function personSheet(member) {
    const s = snap();
    const jobs = s.tasks.filter(task => task.owner_id === member.id).sort((a, b) => a.due_at.localeCompare(b.due_at));
    const content = [
        note(`${member.team_ids.map(teamName).join(', ') || 'No team'}${member.telegram_linked === null ? '' : member.telegram_linked ? ' · on Telegram' : ' · not on Telegram yet'}`),
    ];
    if (jobs.length) {
        content.push(el('div', 'group', el('h3', 'group-title', 'Jobs'), list(...jobs.map(task => {
            const status = jobStatus(task);
            return row({ title: task.title, meta: `${clock(task.due_at)} · ${placeName(task.location_id)}`, end: pill(status.label, status.tone) });
        }))));
    }
    const invite = el('div');
    content.push(invite);
    sheet({
        eyebrow: member.roles.map(roleWord).join(', '), title: member.name, content,
        actions: close => {
            const actions = [];
            if (can('members:manage') && member.active) {
                actions.push(button('Invitation link', async () => {
                    const link = await api('/api/invitations', { member_id: member.id });
                    const box = field('Invitation link', link.telegram_url || link.web_url, { hint: 'Secret and single-use. Send it only to this person. It ends in 24 hours.' });
                    box.input.readOnly = true;
                    invite.replaceChildren(box.wrap, button('Copy link', async () => {
                        await navigator.clipboard.writeText(box.input.value);
                        toast('Link copied.');
                    }, 'small'));
                }));
                if (member.id !== s.me.id) {
                    actions.push(button('Remove access', () => {
                        close();
                        confirmRemove(member);
                    }, 'danger'));
                }
            }
            actions.push(button('Close', close));
            return actions;
        },
    });
}
function confirmRemove(member) {
    sheet({
        eyebrow: 'Remove access', eyebrowTone: 'urgent', title: `Remove ${member.name}?`,
        text: 'They are signed out at once and can no longer see or change anything. Their past actions stay in the activity log.',
        actions: close => [
            button('Keep access', close),
            button('Remove access', async () => {
                await command({ type: 'revoke_member', member_id: member.id });
                close();
                toast(`${memberName(member.id)} no longer has access.`);
                go('crew');
            }, 'danger'),
        ],
    });
}
