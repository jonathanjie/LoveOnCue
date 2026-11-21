// Guests: find a table fast. Arrival and editing open in a sheet so the right person is confirmed.
import { api, command } from '../api.js';
import { can } from '../access.js';
import { placeName, roleWord, ROLES } from '../format.js';
import { icon } from '../icons.js';
import { snap, state } from '../state.js';
import { button, choose, el, empty, errorText, field, groupTitle, list, note, pill, row, sheet, toast } from '../ui.js';
let searchSequence = 0;
let results;
/** Dietary notes are a separate grant. People with only that grant always search with it. */
function sensitive() { return state.guestDietary || !can('guests:seating'); }
async function search() {
    const sequence = ++searchSequence;
    const member = snap().me.id;
    const reply = await api(`/api/guests?q=${encodeURIComponent(state.guestQuery)}&sensitive=${sensitive()}`);
    // Drop late answers for an older query or another signed-in person.
    if (sequence !== searchSequence || snap().me.id !== member)
        return;
    state.guestRows = reply.items;
    drawResults();
}
export function guests(main) {
    const input = el('input');
    input.type = 'search';
    input.value = state.guestQuery;
    input.placeholder = 'Type a name';
    input.autocomplete = 'off';
    input.setAttribute('aria-label', 'Guest name');
    let timer = 0;
    input.addEventListener('input', () => {
        state.guestQuery = input.value;
        window.clearTimeout(timer);
        timer = window.setTimeout(() => {
            if (!state.guestQuery.trim()) {
                searchSequence++; // Drop any answer still on its way for the old text.
                state.guestRows = [];
                drawResults();
                return;
            }
            void search().catch(error => toast(errorText(error), true));
        }, 250);
    });
    main.append(el('label', 'search', icon('search'), input));
    const hint = note('Check the full name before you guide someone. Similar names are different people.');
    main.append(hint);
    if (can('guests:dietary') && can('guests:seating')) {
        const check = el('input');
        check.type = 'checkbox';
        check.checked = state.guestDietary;
        check.addEventListener('change', () => { state.guestDietary = check.checked; void search().catch(error => toast(errorText(error), true)); });
        main.append(el('label', 'check', check, 'Show dietary notes'));
    }
    results = el('section', 'group');
    main.append(results);
    drawResults();
}
function drawResults() {
    if (!results || !results.isConnected)
        return;
    if (!state.guestQuery.trim()) {
        results.replaceChildren(empty('Type part of a name', 'For example “Tan” or “Sarah”.'));
        return;
    }
    const rows = state.guestRows;
    results.replaceChildren(groupTitle(rows.length === 50 ? 'First 50 matches' : `${rows.length} ${rows.length === 1 ? 'match' : 'matches'}`));
    if (!rows.length) {
        results.append(empty('No guest with that name', 'Try part of the name, or ask the coordinator.'));
        return;
    }
    results.append(list(...rows.map(guest => row({
        title: guest.name,
        meta: `Table ${guest.table || 'not set'} · ${placeName(guest.location_id)}${guest.dietary ? ` · ${guest.dietary}` : ''}`,
        end: guest.attendance === 'onsite' ? pill('Arrived', 'done') : pill('Not here yet'),
        onOpen: () => guestSheet(guest),
    }))));
    if (rows.length === 50)
        results.append(note('Type more of the name to see other guests.'));
}
function guestSheet(guest) {
    const table = snap().tables.find(item => item.label === guest.table);
    const place = snap().locations.find(item => item.id === guest.location_id);
    sheet({
        eyebrow: guest.attendance === 'onsite' ? 'Arrived' : 'Not here yet', title: guest.name,
        content: [
            el('p', 'card-body', `Table ${guest.table || 'not set'}${table ? ` · ${table.capacity} seats` : ''} · ${placeName(guest.location_id)}`),
            place?.directions ? note(place.directions) : null,
            guest.dietary ? el('div', 'quote', guest.dietary) : null,
        ],
        actions: close => {
            const actions = [];
            if (can('guests:arrival') && guest.attendance !== 'onsite') {
                actions.push(button(`Yes, ${guest.name.split(' ')[0]} is here`, async () => {
                    await command({ type: 'arrival', person_ids: [guest.id], status: 'onsite' });
                    close();
                    toast(`${guest.name} marked as arrived.`);
                    await search();
                }, 'primary'));
            }
            if (can('guests:manage'))
                actions.push(button('Edit details', async () => { close(); await editGuest(guest.id); }));
            actions.push(button('Close', close));
            return actions;
        },
    });
}
async function editGuest(id) {
    const s = snap();
    const entry = await api(`/api/guests/${encodeURIComponent(id)}/details`);
    const name = field('Name', entry.name);
    const table = choose('Table', [{ id: '', name: 'Not set' }, ...s.tables.map(item => ({ id: item.id, name: `Table ${item.label}` }))], entry.table_id || '');
    const rsvp = choose('Coming?', [{ id: 'yes', name: 'Yes' }, { id: 'no', name: 'No' }, { id: 'unknown', name: 'Not known' }], entry.rsvp);
    const relation = field('Family role', entry.relationship || '', { hint: 'For example father_of_bride. Leave empty if not family. Family members appear on the family liaison’s contact list.' });
    const dietary = field('Dietary notes', entry.dietary || '');
    const phone = field('Private phone', entry.private_phone || '', { hint: 'Only the coordinator and the family liaison can see it.' });
    const role = choose('Helper role', ROLES.filter(item => item !== 'coordinator' && item !== 'couple').map(item => ({ id: item, name: roleWord(item) })));
    const team = choose('Helper team', s.teams);
    sheet({
        eyebrow: 'Edit guest', title: entry.name,
        content: [name.wrap, table.wrap, rsvp.wrap, relation.wrap, dietary.wrap, phone.wrap,
            el('details', 'fold', el('summary', '', 'Make this guest a helper'), el('div', 'fold-body', role.wrap, team.wrap, button('Add as helper', async () => {
                await command({ type: 'create_member', person_id: id, roles: [role.input.value], team_ids: [team.input.value] });
                toast(`${entry.name} is now a helper. Send them an invitation from Crew.`);
            })))],
        actions: close => [
            button('Cancel', close),
            button('Save', async () => {
                await command({ type: 'edit_guest', person_id: id, expected_version: entry.version, name: name.input.value,
                    table_id: table.input.value || null, rsvp: rsvp.input.value, relationship: relation.input.value || null,
                    dietary: dietary.input.value || null, private_phone: phone.input.value || null });
                close();
                toast('Guest details saved.');
                await search();
            }, 'primary'),
        ],
    });
}
