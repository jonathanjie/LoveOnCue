// Places & vendors: directions as a list (no floor plan), vendor contacts with call links.
import {api, command} from '../api.js';
import {can} from '../access.js';
import {clock, teamName} from '../format.js';
import {icon} from '../icons.js';
import {snap} from '../state.js';
import type {Vendor} from '../types.js';
import {button, el, empty, groupTitle, list, note, pill, row, sheet, toast} from '../ui.js';

const VENDOR_WORDS: Record<string, {label: string; tone: '' | 'done' | 'waiting' | 'urgent'}> = {
  expected: {label: 'Expected', tone: 'waiting'}, onsite: {label: 'On site', tone: 'done'},
  late: {label: 'Late', tone: 'urgent'}, complete: {label: 'Finished', tone: ''},
};

export function places(main: HTMLElement): void {
  const s = snap();
  main.append(el('section', 'group', groupTitle('Places', s.locations.length),
    s.locations.length ? list(...s.locations.map(place => row({title: place.name, meta: place.directions, wrapMeta: true}))) : empty('No places yet')));
  if (s.vendors.length) {
    main.append(el('section', 'group', groupTitle('Vendors', s.vendors.length), list(...s.vendors.map(vendor => {
      const status = VENDOR_WORDS[vendor.status] || {label: vendor.status, tone: ''};
      return row({title: vendor.name, meta: `${vendor.category} · ${vendor.contact_name}`, end: pill(status.label, status.tone), onOpen: () => vendorSheet(vendor)});
    }))));
  } else if (!can('vendors:team')) {
    main.append(note('Vendor contacts are shown to the team that works with them. Ask the coordinator for others.'));
  }
  if (can('family:contacts')) main.append(el('section', 'group', button('Family contacts', familyContacts, 'wide')));
}

function vendorSheet(vendor: Vendor): void {
  const call = el('a', 'button wide', icon('phone'), `Call ${vendor.contact_name}`);
  call.href = `tel:${vendor.contact_phone.replace(/[^\d+]/g, '')}`;
  sheet({
    eyebrow: `${vendor.category} · ${teamName(vendor.team_id)}`, title: vendor.name,
    content: [el('p', 'card-body', `${vendor.contact_name} · ${vendor.contact_phone}`), note(`Expected at ${clock(vendor.expected_at)}`), call],
    actions: close => {
      const actions: Node[] = [];
      if (can('vendors:team') && vendor.status !== 'complete') {
        const next = vendor.status === 'onsite' ? 'complete' : 'onsite';
        actions.push(button(next === 'onsite' ? 'They have arrived' : 'They have finished', async () => {
          await command({type: 'vendor_status', vendor_id: vendor.id, status: next});
          close();
          toast(`${vendor.name} marked as ${next === 'onsite' ? 'on site' : 'finished'}.`);
        }, 'primary'));
      }
      actions.push(button('Close', close));
      return actions;
    },
  });
}

async function familyContacts(): Promise<void> {
  const reply = await api<{items: {name: string; relationship: string; private_phone: string | null}[]}>('/api/family/contacts');
  sheet({
    eyebrow: 'Private · do not share', title: 'Family contacts',
    content: [reply.items.length
      ? list(...reply.items.map(person => row({title: person.name, meta: `${person.relationship.replaceAll('_', ' ')} · ${person.private_phone || 'No phone recorded'}`})))
      : empty('No family contacts yet', 'The coordinator adds family roles in Guests.')],
  });
}
