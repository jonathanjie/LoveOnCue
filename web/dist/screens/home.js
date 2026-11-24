// Home: a hub. The state of the day at the top, then tiles that open every section.
import { can, canLookUpGuests, isCoordinator } from '../access.js';
import { approvalStatus, memberName, moved, nowAndNext, relative } from '../format.js';
import { icon } from '../icons.js';
import { go, snap, state } from '../state.js';
import { el, empty, groupTitle, tile } from '../ui.js';
import { crewEntries, notSeen, sendUpdate } from './crew.js';
import { problemSheet } from './review.js';
import { heroJob, myJobs, nowStrip, reportProblem, unreadUpdates, updateCard } from './shared.js';
export function home(main) {
    main.append(nowStrip());
    const urgent = snap().incidents.find(incident => incident.status === 'open' && incident.severity === 'urgent');
    if (urgent && isCoordinator()) {
        const bar = el('button', 'alert-bar', icon('alert'), el('span', 'row-main', urgent.title, el('span', 'row-meta', `Urgent · ${memberName(urgent.reported_by)} · ${relative(urgent.created_at)}`)), icon('chevron', 'chevron'));
        bar.type = 'button';
        bar.addEventListener('click', () => problemSheet(urgent));
        main.append(bar);
    }
    if (isCoordinator())
        coordinatorTiles(main);
    else
        helperHome(main);
}
function coordinatorTiles(main) {
    const s = snap();
    const changes = s.approvals.filter(approval => approvalStatus(approval, s.now).open).length;
    const problems = s.incidents.filter(incident => incident.status === 'open').length;
    const reviewTotal = changes + problems;
    const entries = crewEntries();
    const missing = notSeen(entries).length;
    const movedCount = s.timeline.filter(cue => moved(cue) !== 0).length;
    const { next } = nowAndNext();
    const update = state.brief?.latest_update;
    const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
    main.append(el('div', 'tiles', tile({ icon: 'review', name: 'Review', count: reviewTotal || undefined, tone: reviewTotal ? 'alert' : '',
        status: reviewTotal ? [changes ? plural(changes, 'change', 'changes') : '', problems ? plural(problems, 'problem', 'problems') : ''].filter(Boolean).join(' · ') : 'Nothing to decide',
        onOpen: () => { state.reviewTab = changes || !problems ? 'changes' : 'problems'; go('review'); } }), tile({ icon: 'crew', name: 'Crew', count: missing || undefined, tone: missing ? 'waiting' : '',
        status: missing ? `${plural(missing, 'has', 'have')} not seen their job` : 'Everyone has seen their job',
        onOpen: () => { state.crewTab = missing ? 'not_seen' : 'everyone'; go('crew'); } }), tile({ icon: 'schedule', name: 'Schedule',
        status: `${movedCount ? `${plural(movedCount, 'change', 'changes')} today` : 'No changes'}${next ? ` · next ${relative(next.current_start)}` : ''}`,
        onOpen: () => go('schedule') }), tile({ icon: 'guests', name: 'Guests', count: s.counts.onsite, status: `${s.counts.onsite} of ${s.counts.guests} arrived`, onOpen: () => go('guests') })));
    const small = el('div', 'tiles three');
    if (can('messages:broadcast'))
        small.append(tile({ icon: 'send', name: 'Send an update', small: true, onOpen: sendUpdate }));
    small.append(tile({ icon: 'pin', name: s.vendors.length ? 'Places & vendors' : 'Places', small: true, onOpen: () => go('places') }), tile({ icon: 'book', name: 'Venue notes', small: true, onOpen: () => go('notes') }), tile({ icon: 'alert', name: 'Problems', small: true, onOpen: () => { state.reviewTab = 'problems'; go('review'); } }));
    if (can('wedding:manage'))
        small.append(tile({ icon: 'setup', name: 'Set up', small: true, onOpen: () => go('setup') }));
    if (can('audit:read'))
        small.append(tile({ icon: 'log', name: 'Activity log', small: true, onOpen: () => go('activity') }));
    main.append(small);
    if (update && update.not_read.length) {
        const line = el('p', 'note', `Last update: ${update.read.length} of ${update.total} have read it.`);
        main.append(line);
    }
}
function helperHome(main) {
    const updates = unreadUpdates();
    const newest = updates[0];
    if (newest) {
        const more = updates.length - 1;
        main.append(el('section', 'group', updateCard(newest), more ? el('p', 'note', `${more} more in My jobs.`) : null));
    }
    const next = myJobs()[0];
    const jobs = el('section', 'group', groupTitle('Your next job'));
    jobs.append(next ? heroJob(next) : empty('No job for you right now', 'New jobs show up here and in Telegram.', 'clear'));
    main.append(jobs);
    const tiles = el('div', 'tiles');
    if (canLookUpGuests())
        tiles.append(tile({ icon: 'guests', name: 'Find a guest', status: 'Table and arrival', onOpen: () => go('guests') }));
    if (can('incidents:report'))
        tiles.append(tile({ icon: 'alert', name: 'Report a problem', status: 'Tell the coordinator', onOpen: reportProblem }));
    tiles.append(tile({ icon: 'pin', name: snap().vendors.length ? 'Places & vendors' : 'Places', status: 'Directions and contacts', onOpen: () => go('places') }));
    if (can('knowledge:read'))
        tiles.append(tile({ icon: 'book', name: 'Venue notes', status: 'Lifts, parking, rules', onOpen: () => go('notes') }));
    main.append(tiles);
}
