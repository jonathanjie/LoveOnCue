// Pieces used by more than one screen: the now/next strip, job actions, updates, report forms.
import {command} from '../api.js';
import {can} from '../access.js';
import {clock, isOpenJob, jobStatus, moved, noticeText, nowAndNext, placeName, relative} from '../format.js';
import {icon} from '../icons.js';
import {snap} from '../state.js';
import type {Notice, Task} from '../types.js';
import {area, button, chips, el, sheet, toast} from '../ui.js';

export function nowStrip(): HTMLElement {
  const {now, next} = nowAndNext();
  const strip = el('div', 'strip');
  strip.setAttribute('aria-label', 'Now and next on the schedule');
  strip.append(el('span', 'strip-label', 'Now'));
  strip.append(el('span', 'strip-value', now ? el('span', 'time', clock(now.current_start)) : '', now ? ` ${now.title}` : 'Nothing has started yet'));
  strip.append(el('span', 'strip-label', 'Next'));
  if (next) {
    const value = el('span', 'strip-value');
    if (moved(next) !== 0) value.append(el('s', 'time', clock(next.planned_start)));
    value.append(el('span', 'time', clock(next.current_start)), ` ${next.title}`);
    strip.append(value);
  } else {
    strip.append(el('span', 'strip-value', 'Nothing else today'));
  }
  return strip;
}

/** Updates sent to me that still need "I've read this". */
export function unreadUpdates(): Notice[] {
  return snap().notifications.filter(notice => !notice.acknowledged_at && notice.topic !== 'bot_reply');
}

export function updateCard(notice: Notice): HTMLElement {
  const text = el('p', 'update-text', noticeText(notice.message));
  text.addEventListener('click', () => text.classList.toggle('is-open'));
  return el('div', 'update',
    el('div', 'update-main', el('div', 'update-from', `Update · ${clock(notice.created_at)}`), text),
    button('Read', async () => {
      await command({type: 'acknowledge_notification', notification_id: notice.id});
      toast('Marked as read. The coordinator can see it.');
    }, 'small primary'));
}

/** My open jobs, soonest first. */
export function myJobs(): Task[] {
  return snap().tasks.filter(task => task.mine && isOpenJob(task));
}

/** One main action for a job: "Got it" first, then "Done". */
export function jobActions(task: Task): HTMLElement | null {
  if (!task.can_edit || !isOpenJob(task)) return null;
  const act = (action: string, message: string) => async () => {
    await command({type: 'task_action', task_id: task.id, action, expected_version: task.version});
    toast(message);
  };
  const actions = el('div', 'card-actions');
  if (!task.acknowledged_at) {
    actions.append(button('Got it', act('acknowledge', 'Thanks. The coordinator can see you have it.'), 'primary'));
    return actions;
  }
  const done = button('Done', act('complete', 'Marked as done.'), 'primary');
  done.disabled = task.blocked_by.length > 0;
  if (task.state === 'pending') {
    const start = button('I’ve started', act('start', 'Marked as started.'));
    start.disabled = task.blocked_by.length > 0;
    actions.append(start);
  }
  actions.append(done);
  return actions;
}

export function heroJob(task: Task): HTMLElement {
  const status = jobStatus(task);
  const hero = el('article', `hero${task.overdue ? ' is-late' : ''}`,
    el('div', 'hero-when', el('span', 'time', clock(task.due_at)), el('span', '', task.overdue ? 'Late' : relative(task.due_at)),
      status.label === 'Got it' || status.label === 'Doing it' ? el('span', `pill ${status.tone}`, status.label) : null),
    el('h1', 'hero-title', task.title),
    el('p', 'hero-where', icon('pin'), placeName(task.location_id)),
    task.instructions ? el('p', 'hero-detail', task.instructions) : null,
    task.blocked_by.length ? el('p', 'hero-detail error-text', `Waiting for: ${task.blocked_by.join(', ')}`) : null,
    jobActions(task));
  return hero;
}

/** "Report a problem" sheet. The report goes to the coordinator and the teams it concerns. */
export function reportProblem(): void {
  if (!can('incidents:report')) return;
  const title = el('input');
  title.className = 'input';
  title.maxLength = 160;
  title.placeholder = 'For example: bridal car has a flat tyre';
  const titleWrap = el('label', 'field', el('span', 'field-label', 'What is the problem?'), title);
  const details = area('More detail', '', 'Where, who is affected, what you need.');
  const urgency = chips('How urgent?', [{id: 'normal', name: 'Can wait a little'}, {id: 'urgent', name: 'Urgent'}], false, ['normal']);
  sheet({
    eyebrow: 'Report a problem', title: 'Tell the coordinator',
    content: [titleWrap, details.wrap, urgency.wrap],
    actions: close => [
      button('Cancel', close),
      button('Send report', async () => {
        if (title.value.trim().length < 3) throw new Error('Write a short title first.');
        await command({type: 'report_incident', kind: 'logistics', title: title.value.trim(),
          details: details.input.value.trim() || title.value.trim(), severity: urgency.values()[0] || 'normal'});
        close();
        toast('Sent. The coordinator has it.');
      }, 'primary'),
    ],
  });
}
