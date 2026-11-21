// What to show, from the grants in the signed-in person's snapshot.
// This only hides buttons. The server checks every read and command again.
import { snap } from './state.js';
export function can(grant) {
    const grants = snap().me.grants;
    return grants.includes('*') || grants.includes(grant);
}
export function isCoordinator() { return snap().me.roles.includes('coordinator'); }
export function canLookUpGuests() { return can('guests:seating') || can('guests:dietary'); }
