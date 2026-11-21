// Schedule: the whole day on one line per cue, with a "Now" line and moved times flagged.
import {command} from '../api.js';
import {can, isCoordinator} from '../access.js';
import {approvalStatus, clock, minutesBetween, moved, placeName, shift, teamName} from '../format.js';
import {go, rerender, snap, state} from '../state.js';
import type {Cue} from '../types.js';
import {area, button, chips, el, empty, note, pill, sheet, toast} from '../ui.js';
import {approvalSheet} from './review.js';

function cueRow(cue: Cue): HTMLLIElement {
  const s = snap();
  const shiftMinutes = moved(cue);
  const pending = s.approvals.find(approval => approvalStatus(approval, s.now).open && approval.changes.some(change => change.item_id === cue.id));
  const mine = cue.team_ids.some(team => s.me.team_ids.includes(team));
  const classes = ['cue', cue.status === 'live' ? 'is-live' : '', cue.status === 'complete' ? 'is-done' : '', mine && !isCoordinator() ? 'is-mine' : ''];
  let flag: HTMLElement | null = null;
  if (pending && isCoordinator()) flag = pill('Change?', 'waiting');
  else if (shiftMinutes !== 0 && cue.status !== 'complete') flag = pill(shift(shiftMinutes), 'change');
  else if (cue.latest_end && cue.status !== 'complete') flag = pill(`ends by ${clock(cue.latest_end)}`);
  const body = el('button', 'cue-body', el('span', 'cue-title', cue.title), el('span', 'cue-meta', placeName(cue.location_id)), flag ? el('span', 'cue-flag', flag) : null);
  body.type = 'button';
  body.setAttribute('aria-label', `${clock(cue.current_start)} ${cue.title}. Open details.`);
  body.addEventListener('click', () => cueSheet(cue));
  return el('li', classes.filter(Boolean).join(' '),
    el('div', 'cue-time', shiftMinutes !== 0 ? el('s', '', clock(cue.planned_start)) : null, clock(cue.current_start)),
    el('div', 'cue-dot'), body);
}

export function schedule(main: HTMLElement): void {
  const s = snap();
  const changes = s.timeline.filter(cue => moved(cue) !== 0).length;
  main.append(el('div', 'screen-head', el('p', 'screen-sub',
    changes ? `${changes} ${changes === 1 ? 'cue has' : 'cues have'} moved today.` : 'No changes today.')));
  if (!s.timeline.length) {
    main.append(empty('No schedule yet', isCoordinator() ? 'Add cues in Set up.' : 'The coordinator has not added the schedule yet.'));
    return;
  }
  const finished = s.timeline.filter(cue => cue.status === 'complete');
  if (finished.length) {
    const fold = el('button', 'folded', `${finished.length} finished · ${state.showFinishedCues ? 'hide' : 'show'}`);
    fold.type = 'button';
    fold.addEventListener('click', () => { state.showFinishedCues = !state.showFinishedCues; rerender(); });
    main.append(fold);
  }
  const visible = s.timeline.filter(cue => cue.status !== 'complete' || state.showFinishedCues);
  // The "Now" line goes after the live cues and before the first cue still to come.
  const before = visible.filter(cue => cue.status !== 'scheduled');
  const after = visible.filter(cue => cue.status === 'scheduled');
  if (before.length) main.append(el('ol', 'cues compact', ...before.map(cueRow)));
  main.append(el('div', 'now-line', el('div', 'now-line-label', 'Now', el('span', 'time', clock(s.now)))));
  if (after.length) main.append(el('ol', 'cues compact', ...after.map(cueRow)));
  main.append(note('Tap a cue for details.'));
}

function cueSheet(cue: Cue): void {
  const s = snap();
  const shiftMinutes = moved(cue);
  const ends = new Date(new Date(cue.current_start).getTime() + cue.duration_minutes * 60000).toISOString();
  const pending = s.approvals.find(approval => approvalStatus(approval, s.now).open && approval.changes.some(change => change.item_id === cue.id));
  const lines: (Node | null)[] = [
    el('p', 'card-body', `${clock(cue.current_start)}–${clock(ends)} · ${placeName(cue.location_id)}`),
    shiftMinutes !== 0 ? note(`Moved ${shift(shiftMinutes)} from ${clock(cue.planned_start)}.`) : null,
    cue.latest_end ? note(`Must end by ${clock(cue.latest_end)}.`) : null,
    cue.actual_start ? note(`Started ${clock(cue.actual_start)}${cue.actual_end ? `, finished ${clock(cue.actual_end)}` : ''}.`) : null,
    note(`Teams: ${cue.team_ids.map(teamName).join(', ') || 'none'}`),
    cue.instructions ? el('div', 'quote', cue.instructions) : null,
  ];
  const canReportDelay = cue.status === 'scheduled' && can('timeline:propose') && (isCoordinator() || cue.team_ids.some(team => s.me.team_ids.includes(team)));
  sheet({
    eyebrow: cue.status === 'live' ? 'Happening now' : cue.status === 'complete' ? 'Finished' : 'Coming up',
    eyebrowTone: cue.status === 'live' ? 'change' : '', title: cue.title, content: lines,
    actions: close => {
      const actions: Node[] = [];
      if (pending && can('timeline:approve')) actions.push(button('Review the change', () => { close(); approvalSheet(pending); }, 'primary'));
      if (can('timeline:manage') && cue.status !== 'complete') {
        const started = cue.status === 'scheduled';
        actions.push(button(started ? 'It has started' : 'It has finished', async () => {
          await command({type: 'timeline_action', item_id: cue.id, action: started ? 'start' : 'complete', expected_timeline_version: s.wedding.timeline_version});
          close();
          toast(started ? `${cue.title} marked as started.` : `${cue.title} marked as finished.`);
        }));
      }
      if (canReportDelay && !pending) actions.push(button('Report a delay', () => { close(); delaySheet(cue); }));
      actions.push(button('Close', close));
      return actions;
    },
  });
}

function delaySheet(cue: Cue): void {
  const minutes = chips('How much later?', [5, 10, 15, 20, 30, 45].map(value => ({id: String(value), name: `${value} min`})), false, ['10']);
  const reason = area('Why?', '', 'The coordinator sees your words before deciding.');
  const s = snap();
  const later = s.timeline.filter(item => item.status === 'scheduled' && minutesBetween(cue.current_start, item.current_start) >= 0).length;
  sheet({
    eyebrow: 'Report a delay', title: cue.title,
    text: `Nothing moves until the coordinator approves. Up to ${later} ${later === 1 ? 'cue' : 'cues'} may move.`,
    content: [minutes.wrap, reason.wrap],
    actions: close => [
      button('Cancel', close),
      button('Send to coordinator', async () => {
        if (!reason.input.value.trim()) throw new Error('Write one line about why.');
        await command({type: 'propose_delay', item_id: cue.id, minutes: Number(minutes.values()[0] || '10'), reason: reason.input.value.trim()});
        close();
        toast('Sent to the coordinator for a decision.');
        if (isCoordinator()) go('review');
      }, 'primary'),
    ],
  });
}
