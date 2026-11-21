// Set up (coordinator): build the roster, places, jobs and schedule. Same commands as before,
// with times entered as local clock times on the event date.
import {api, command} from '../api.js';
import {can} from '../access.js';
import {eventTime, roleWord, ROLES} from '../format.js';
import {snap} from '../state.js';
import type {ImportPreview} from '../types.js';
import {area, button, choose, el, field, note, sheet, toast} from '../ui.js';

function fold(title: string, ...body: Node[]): HTMLDetailsElement {
  return el('details', 'fold', el('summary', '', title), el('div', 'fold-body', ...body));
}

function save(label: string, action: () => Promise<void>, done: string): HTMLButtonElement {
  return button(label, async () => { await action(); toast(done); }, 'primary wide');
}

function timeField(label: string, value: string, hint = ''): {wrap: HTMLLabelElement; input: HTMLInputElement} {
  return field(label, value, {type: 'time', hint: hint || `On ${snap().wedding.event_date}, wedding time zone.`});
}

export function setup(main: HTMLElement): void {
  const s = snap();
  const teams = s.teams;
  const places = s.locations;

  if (s.wedding.status !== 'archived') {
    const live = s.wedding.status === 'live';
    main.append(el('div', 'card',
      el('div', 'card-title', live ? 'Job reminders are on' : 'Job reminders are off'),
      el('p', 'card-body', live ? 'Helpers get reminders before their jobs are due.' : 'Turn on when the roster and schedule are ready.'),
      el('div', 'card-actions', button(live ? 'Pause reminders' : 'Turn on reminders', () => confirmStatus(live ? 'draft' : 'live'), live ? '' : 'primary'))));
  }

  const group = el('section', 'group');
  const team = field('Team name');
  group.append(fold('Add a team', team.wrap, save('Add team', () => command({type: 'create_team', name: team.input.value}), 'Team added.')));

  const name = field('Name');
  const role = choose('Role', ROLES.map(item => ({id: item, name: roleWord(item)})), 'helper');
  const memberTeam = choose('Team', teams);
  group.append(fold('Add a helper', name.wrap, role.wrap, memberTeam.wrap, note('Then send them an invitation link from Crew.'),
    save('Add helper', () => command({type: 'create_member', name: name.input.value, roles: [role.input.value], team_ids: [memberTeam.input.value]}), 'Helper added.')));

  const placeName = field('Place name');
  const directions = area('Directions');
  group.append(fold('Add a place', placeName.wrap, directions.wrap,
    save('Add place', () => command({type: 'create_location', name: placeName.input.value, directions: directions.input.value, x: 50, y: 50}), 'Place added.')));

  const label = field('Table number or name');
  const seats = field('Seats', '10', {type: 'number'});
  const tablePlace = choose('Place', places);
  group.append(fold('Add a table', label.wrap, seats.wrap, tablePlace.wrap,
    save('Add table', () => command({type: 'create_table', label: label.input.value, capacity: Number(seats.input.value), location_id: tablePlace.input.value, x: 50, y: 50}), 'Table added.')));

  const jobTitle = field('Job');
  const jobText = area('What to do');
  const owner = choose('Who', s.members.filter(member => member.active).map(member => ({id: member.id, name: member.name})));
  const jobTeam = choose('Team', teams);
  const jobPlace = choose('Where', places);
  const due = timeField('Due at', '18:00');
  const after = choose('Only after', [{id: '', name: 'Nothing'}, ...s.tasks.map(task => ({id: task.id, name: task.title}))]);
  group.append(fold('Add a job', jobTitle.wrap, jobText.wrap, owner.wrap, jobTeam.wrap, jobPlace.wrap, due.wrap, after.wrap,
    save('Add job', () => command({type: 'create_task', title: jobTitle.input.value, instructions: jobText.input.value, owner_id: owner.input.value,
      team_id: jobTeam.input.value, location_id: jobPlace.input.value, due_at: eventTime(due.input.value),
      depends_on_ids: after.input.value ? [after.input.value] : []}), 'Job added.')));

  const cueTitle = field('Cue');
  const start = timeField('Starts at', '21:00');
  const minutes = field('Minutes', '15', {type: 'number'});
  const cueTeam = choose('Team', teams);
  const cuePlace = choose('Where', places);
  const cueAfter = choose('Starts after', [{id: '', name: 'Nothing'}, ...s.timeline.map(cue => ({id: cue.id, name: cue.title}))]);
  const latest = timeField('Must end by (optional)', '', 'Leave empty if there is no hard limit.');
  group.append(fold('Add a schedule cue', cueTitle.wrap, start.wrap, minutes.wrap, cueTeam.wrap, cuePlace.wrap, cueAfter.wrap, latest.wrap,
    save('Add cue', () => command({type: 'create_timeline_item', title: cueTitle.input.value, starts_at: eventTime(start.input.value),
      duration_minutes: Number(minutes.input.value), team_ids: [cueTeam.input.value], location_id: cuePlace.input.value,
      depends_on_ids: cueAfter.input.value ? [cueAfter.input.value] : [], latest_end: latest.input.value ? eventTime(latest.input.value) : null}), 'Cue added.')));

  const vendor = field('Vendor name');
  const category = field('What they do', '', {placeholder: 'Catering, florist, band…'});
  const contact = field('Contact person');
  const phone = field('Contact phone', '', {type: 'tel'});
  const vendorTeam = choose('Team that works with them', teams);
  const expected = timeField('Expected at', '16:00');
  group.append(fold('Add a vendor', vendor.wrap, category.wrap, contact.wrap, phone.wrap, vendorTeam.wrap, expected.wrap,
    save('Add vendor', () => command({type: 'create_vendor', name: vendor.input.value, category: category.input.value, contact_name: contact.input.value,
      contact_phone: phone.input.value, team_id: vendorTeam.input.value, expected_at: eventTime(expected.input.value)}), 'Vendor added.')));

  if (can('guests:manage')) group.append(guestImport());
  main.append(group);

  const exportLink = el('a', 'button', 'Download guest list');
  exportLink.href = '/api/export/guests.csv';
  exportLink.download = 'wedding-guests.csv';
  const actions = el('div', 'card-actions', exportLink);
  if (s.wedding.status !== 'archived') actions.append(button('Archive wedding', () => confirmStatus('archived'), 'danger'));
  main.append(el('section', 'group', actions));
}

function guestImport(): HTMLDetailsElement {
  const csv = area('Guest list (CSV)', 'name,table,rsvp\nExample Guest,19,yes', 'Columns: name, table, rsvp, dietary. New guests are added; nobody is overwritten.');
  const upload = field('Or load a CSV file', '', {type: 'file'});
  upload.input.accept = '.csv,text/csv';
  upload.input.addEventListener('change', () => {
    const chosen = upload.input.files?.[0];
    if (chosen && chosen.size < 200000) void chosen.text().then(text => { csv.input.value = text; });
  });
  const preview = el('div');
  return fold('Import guests', upload.wrap, csv.wrap, button('Check the list', async () => {
    const result = await api<ImportPreview>('/api/import/guests', {csv: csv.input.value});
    preview.replaceChildren(el('p', 'card-body', `${result.count} guests · ${result.error_count} problems`),
      ...result.errors.map(error => el('p', 'note error-text', error)),
      ...result.sample.map(guest => note(`${guest.name} · table ${guest.table_id} · ${guest.rsvp}`)));
    if (!result.error_count) preview.append(save('Import these guests', () => command({type: 'apply_guest_import', import_id: result.id}), 'Guests imported.'));
  }), preview);
}

function confirmStatus(target: 'draft' | 'live' | 'archived'): void {
  const words = {
    live: {title: 'Turn on job reminders?', text: 'Helpers get reminders using the current schedule, roster and clock.', button: 'Turn on'},
    draft: {title: 'Pause job reminders?', text: 'New reminders stop. Messages already queued and direct reports still go out.', button: 'Pause'},
    archived: {title: 'Archive the wedding?', text: 'Everything becomes read-only and you cannot undo this here. Download the guest list first.', button: 'Archive'},
  }[target];
  sheet({
    eyebrow: 'Set up', eyebrowTone: target === 'archived' ? 'urgent' : '', title: words.title, text: words.text,
    actions: close => [
      button('Cancel', close),
      button(words.button, async () => {
        await command({type: 'set_wedding_status', status: target});
        close();
        toast('Done.');
      }, target === 'archived' ? 'danger' : 'primary'),
    ],
  });
}
