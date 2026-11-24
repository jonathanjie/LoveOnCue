// Venue notes: search the approved reference text. The coordinator checks new notes before anyone sees them.
import { api, command } from '../api.js';
import { can } from '../access.js';
import { clock } from '../format.js';
import { icon } from '../icons.js';
import { snap } from '../state.js';
import { area, button, choose, el, empty, errorText, field, groupTitle, list, note, pill, row, sheet, toast } from '../ui.js';
const STATUS = {
    draft: { label: 'Not checked yet', tone: 'waiting' }, approved: { label: 'In use', tone: 'done' }, retired: { label: 'Retired', tone: '' },
};
export function notes(main) {
    const input = el('input');
    input.type = 'search';
    input.placeholder = 'For example: service lift';
    input.setAttribute('aria-label', 'Search venue notes');
    const results = el('section', 'group');
    const run = async () => {
        const query = input.value.trim();
        if (!query) {
            results.replaceChildren();
            return;
        }
        const reply = await api(`/api/knowledge?q=${encodeURIComponent(query)}`);
        results.replaceChildren(groupTitle('Answers from the venue notes'), reply.items.length
            ? list(...reply.items.map(hit => row({ title: hit.excerpt, meta: `${hit.title || hit.source} · line ${hit.line}`, wrapMeta: true })))
            : empty('Nothing found', 'Ask the coordinator in chat.'));
    };
    let timer = 0;
    input.addEventListener('input', () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => void run().catch(error => toast(errorText(error), true)), 300);
    });
    main.append(el('label', 'search', icon('search'), input), results);
    if (can('knowledge:manage')) {
        const docs = snap().knowledge;
        main.append(el('section', 'group', groupTitle('All notes', docs.length), docs.length ? list(...docs.map(doc => {
            const status = STATUS[doc.status] || { label: doc.status, tone: '' };
            return row({ title: doc.title, meta: `${doc.source_name} · version ${doc.revision}`, end: pill(status.label, status.tone), onOpen: () => docSheet(doc) });
        })) : empty('No notes yet'), el('div', 'group', button('Add a note', addNote, 'wide'))));
    }
}
function docSheet(doc) {
    sheet({
        eyebrow: (STATUS[doc.status] || { label: doc.status }).label, title: doc.title,
        content: [note(`${doc.source_name} · version ${doc.revision}${doc.verified_at ? ` · checked ${clock(doc.verified_at)}` : ''}`),
            doc.text !== null ? el('pre', 'source', doc.text) : null,
            note('Notes are reference text for answers. They never give the assistant permission to change anything.')],
        actions: close => {
            const actions = [];
            if (doc.status === 'draft')
                actions.push(button('Checked, use it', async () => {
                    await command({ type: 'review_knowledge', document_id: doc.id, decision: 'approve' });
                    close();
                    toast('The note is now in use.');
                }, 'primary'));
            if (doc.status !== 'retired')
                actions.push(button('Retire', async () => {
                    await command({ type: 'review_knowledge', document_id: doc.id, decision: 'retire' });
                    close();
                    toast('The note is retired.');
                }));
            actions.push(button('Close', close));
            return actions;
        },
    });
}
function addNote() {
    const title = field('Title');
    const source = field('Source', '', { hint: 'File name or where it came from.' });
    const text = area('Text', '', 'Plain text or Markdown, up to 60,000 characters.');
    text.input.maxLength = 60000;
    const file = field('Or load a text file', '', { type: 'file' });
    file.input.accept = '.txt,.md,text/plain,text/markdown';
    file.input.addEventListener('change', () => {
        const chosen = file.input.files?.[0];
        if (!chosen)
            return;
        if (chosen.size > 60000) {
            toast('That file is larger than 60 KB.', true);
            return;
        }
        source.input.value = chosen.name;
        void chosen.text().then(content => { text.input.value = content; });
    });
    const audience = choose('Who can see it?', [{ id: '', name: 'Every helper' }, ...snap().teams]);
    sheet({
        eyebrow: 'Add a note', title: 'New venue note', text: 'Nobody sees it until you check it and tap "Checked, use it".',
        content: [title.wrap, source.wrap, file.wrap, text.wrap, audience.wrap],
        actions: close => [
            button('Cancel', close),
            button('Save', async () => {
                await command({ type: 'add_knowledge', title: title.input.value, source_name: source.input.value || 'Typed in LoveOnCue',
                    text: text.input.value, audience_team_ids: audience.input.value ? [audience.input.value] : [] });
                close();
                toast('Saved. Check it in the list to put it in use.');
            }, 'primary'),
        ],
    });
}
