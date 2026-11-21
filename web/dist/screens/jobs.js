// My jobs (helper): updates to read, my jobs in order, and the schedule changes I asked for.
import { approvalStatus, clock, isOpenJob, jobStatus, noticeText, placeName } from '../format.js';
import { snap } from '../state.js';
import { el, empty, groupTitle, list, pill, row, sheet } from '../ui.js';
import { heroJob, jobActions, myJobs, unreadUpdates, updateCard } from './shared.js';
/** Count for the My jobs tab: unread updates and jobs not yet seen. */
export function jobsCount() {
    return unreadUpdates().length + myJobs().filter(task => !task.acknowledged_at).length;
}
export function jobs(main) {
    const s = snap();
    const updates = unreadUpdates();
    if (updates.length)
        main.append(el('section', 'group', groupTitle('New for you', updates.length), ...updates.map(updateCard)));
    const open = myJobs();
    const [next, ...later] = open;
    const jobsSection = el('section', 'group', groupTitle('Your jobs', open.length));
    if (!next)
        jobsSection.append(empty('No open jobs', 'New jobs show up here and in Telegram.'));
    else {
        jobsSection.append(heroJob(next));
        if (later.length)
            jobsSection.append(el('div', 'group', list(...later.map(task => {
                const status = jobStatus(task);
                return row({ title: task.title, meta: `${clock(task.due_at)} · ${placeName(task.location_id)}`, end: pill(status.label, status.tone), onOpen: () => {
                        sheet({ eyebrow: `${clock(task.due_at)} · ${placeName(task.location_id)}`, title: task.title,
                            content: [task.instructions ? el('p', 'card-body', task.instructions) : null, jobActions(task)] });
                    } });
            }))));
    }
    main.append(jobsSection);
    const finished = s.tasks.filter(task => task.mine && !isOpenJob(task));
    if (finished.length)
        main.append(el('section', 'group', groupTitle('Done', finished.length), list(...finished.map(task => row({ title: task.title, meta: clock(task.completed_at || task.due_at), end: pill(jobStatus(task).label, 'done') })))));
    // Non-coordinators only see their own proposals in the snapshot.
    if (s.approvals.length)
        main.append(el('section', 'group', groupTitle('Delays you reported'), list(...s.approvals.map(approval => {
            const status = approvalStatus(approval, s.now);
            return row({ title: approval.title, meta: approval.decision_note ? `Coordinator: ${approval.decision_note}` : `Sent ${clock(approval.created_at)}`,
                end: pill(status.open ? 'Waiting' : status.label, status.open ? 'waiting' : status.tone) });
        }))));
    const read = s.notifications.filter(notice => notice.acknowledged_at && notice.topic !== 'bot_reply').slice(0, 5);
    if (read.length)
        main.append(el('section', 'group', groupTitle('Read'), list(...read.map(notice => row({ title: noticeText(notice.message).split('\n')[0] || 'Update', meta: `Read ${clock(notice.acknowledged_at)}` })))));
}
