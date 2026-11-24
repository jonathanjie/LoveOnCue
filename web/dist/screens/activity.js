// Activity log (coordinator): every recorded change in plain words. Raw detail on request.
import { api } from '../api.js';
import { clock, eventWords, memberName } from '../format.js';
import { el, empty, errorText, list, note, row, sheet, toast } from '../ui.js';
/** Audit actors are member IDs, or the assistant and background delivery. */
function actorName(actorId) {
    if (actorId === 'agent')
        return 'Assistant';
    if (actorId === 'system' || actorId === 'worker')
        return 'Automatic';
    return memberName(actorId);
}
export function activity(main) {
    const holder = el('div', '', note('Loading…'));
    main.append(note('Changes made in LoveOnCue, newest first. This is an application log, not a tamper-proof record.'), holder);
    void api('/api/audit').then(reply => {
        if (!holder.isConnected)
            return;
        if (!reply.items.length) {
            holder.replaceChildren(empty('Nothing recorded yet'));
            return;
        }
        holder.replaceChildren(list(...reply.items.map(entry => row({
            title: eventWords(entry.event_type),
            meta: `${clock(entry.created_at)} · ${actorName(entry.actor_id)}`,
            onOpen: () => sheet({ eyebrow: clock(entry.created_at), title: eventWords(entry.event_type), content: [el('pre', 'source', JSON.stringify(entry.detail, null, 2))] }),
        }))));
    }).catch(error => toast(errorText(error), true));
}
