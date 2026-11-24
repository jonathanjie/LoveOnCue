// Shared client state. Everything here is a cached copy of server state, never an authority.
import type {Brief, Config, Guest, Snapshot} from './types.js';

export type Route = 'home' | 'schedule' | 'review' | 'crew' | 'guests' | 'jobs' | 'places' | 'notes' | 'setup' | 'activity';

export const state = {
  snapshot: undefined as Snapshot | undefined,
  config: undefined as Config | undefined,
  brief: undefined as Brief | undefined,
  csrf: '',
  /** Increases on every sign-in, so late responses for an old session are dropped. */
  sessionEpoch: 0,
  healthy: true,
  lastRefresh: 0,
  route: 'home' as Route,
  reviewTab: 'changes' as 'changes' | 'problems',
  crewTab: 'not_seen' as 'not_seen' | 'got_it' | 'everyone',
  guestQuery: '',
  guestDietary: false,
  guestRows: [] as Guest[],
  showFinishedCues: false,
};

/** The loaded snapshot. Screens only render after sign-in, so it is always present there. */
export function snap(): Snapshot {
  if (!state.snapshot) throw new Error('Not signed in.');
  return state.snapshot;
}

let renderer: () => void = () => {};
export function setRenderer(next: () => void): void { renderer = next; }
/** Draw the current route again from the cached state. */
export function rerender(): void { renderer(); }

export function go(route: Route): void {
  state.route = route;
  window.scrollTo(0, 0);
  renderer();
}
