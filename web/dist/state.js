export const state = {
    snapshot: undefined,
    config: undefined,
    brief: undefined,
    csrf: '',
    /** Increases on every sign-in, so late responses for an old session are dropped. */
    sessionEpoch: 0,
    healthy: true,
    lastRefresh: 0,
    route: 'home',
    reviewTab: 'changes',
    crewTab: 'not_seen',
    guestQuery: '',
    guestDietary: false,
    guestRows: [],
    showFinishedCues: false,
};
/** The loaded snapshot. Screens only render after sign-in, so it is always present there. */
export function snap() {
    if (!state.snapshot)
        throw new Error('Not signed in.');
    return state.snapshot;
}
let renderer = () => { };
export function setRenderer(next) { renderer = next; }
/** Draw the current route again from the cached state. */
export function rerender() { renderer(); }
export function go(route) {
    state.route = route;
    window.scrollTo(0, 0);
    renderer();
}
