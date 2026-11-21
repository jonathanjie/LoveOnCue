// LoveOnCue Mini App shell: sign-in, top bar, tab bar, routing and refresh.
// Chat lives in Telegram. This app covers what chat is bad at: the whole picture and decisions.
import {api, setAfterCommand} from './api.js';
import {can, canLookUpGuests, isCoordinator} from './access.js';
import {clock, roleWord} from './format.js';
import {art, icon, wordmark, type IconName} from './icons.js';
import {go, rerender, setRenderer, snap, state, type Route} from './state.js';
import type {Brief, Config, Snapshot} from './types.js';
import {button, closeAllSheets, el, errorText, isBusy, list, note, row, sheet, sheetOpen, toast} from './ui.js';
import {activity} from './screens/activity.js';
import {crew} from './screens/crew.js';
import {guests} from './screens/guests.js';
import {home} from './screens/home.js';
import {jobs, jobsCount} from './screens/jobs.js';
import {notes} from './screens/notes.js';
import {places} from './screens/places.js';
import {review, reviewCount} from './screens/review.js';
import {schedule} from './screens/schedule.js';
import {setup} from './screens/setup.js';

type TelegramWebApp = {
  initData: string; colorScheme?: 'light' | 'dark'; ready: () => void; expand: () => void;
  onEvent?: (event: string, handler: () => void) => void;
  BackButton?: {show: () => void; hide: () => void; onClick: (handler: () => void) => void};
};
declare global { interface Window { Telegram?: {WebApp?: TelegramWebApp} } }

const root = document.querySelector<HTMLDivElement>('#app')!;
const telegram = (): TelegramWebApp | undefined => window.Telegram?.WebApp;

// ---------- Routes ----------

type Tab = {route: Route; label: string; icon: IconName; count?: () => number};
const SCREENS: Record<Route, {title: string; draw: (main: HTMLElement) => void}> = {
  home: {title: 'Home', draw: home}, schedule: {title: 'Schedule', draw: schedule}, review: {title: 'Review', draw: review},
  crew: {title: 'Crew', draw: crew}, guests: {title: 'Guests', draw: guests}, jobs: {title: 'My jobs', draw: jobs},
  places: {title: 'Places & vendors', draw: places}, notes: {title: 'Venue notes', draw: notes},
  setup: {title: 'Set up', draw: setup}, activity: {title: 'Activity log', draw: activity},
};

function tabs(): Tab[] {
  const result: Tab[] = [{route: 'home', label: 'Home', icon: 'home'}];
  if (isCoordinator()) {
    result.push({route: 'schedule', label: 'Schedule', icon: 'schedule'}, {route: 'review', label: 'Review', icon: 'review', count: reviewCount},
      {route: 'crew', label: 'Crew', icon: 'crew'});
  } else {
    result.push({route: 'jobs', label: 'My jobs', icon: 'jobs', count: jobsCount}, {route: 'schedule', label: 'Schedule', icon: 'schedule'});
  }
  if (canLookUpGuests()) result.push({route: 'guests', label: 'Guests', icon: 'guests'});
  return result;
}

function allowed(route: Route): boolean {
  switch (route) {
    case 'review': case 'crew': return isCoordinator();
    case 'guests': return canLookUpGuests();
    case 'setup': return can('wedding:manage');
    case 'activity': return can('audit:read');
    case 'notes': return can('knowledge:read');
    default: return true;
  }
}

// ---------- Drawing ----------

function topbar(): HTMLElement {
  const s = snap();
  const who = el('button', 'topbar-names',
    el('div', 'topbar-couple', s.wedding.name, state.config?.demo ? el('span', 'topbar-tag', 'Rehearsal') : null),
    el('div', 'topbar-me', `${s.me.name} · ${s.me.roles.map(roleWord).join(', ')}`));
  who.type = 'button';
  who.setAttribute('aria-label', state.config?.demo ? `Rehearsal: signed in as ${s.me.name}. Switch person` : `Signed in as ${s.me.name}. Account`);
  who.addEventListener('click', accountSheet);
  const live = el('div', `clock-state${state.healthy ? '' : ' is-stale'}`, state.healthy ? 'Live' : 'Offline');
  return el('header', 'topbar', who, el('div', 'clock', el('div', 'clock-time', clock(s.now)), live));
}

function tabbar(): HTMLElement {
  const nav = el('nav', 'tabbar');
  nav.setAttribute('aria-label', 'Sections');
  const current = tabs().some(tab => tab.route === state.route) ? state.route : 'home';
  for (const tab of tabs()) {
    const count = tab.count?.() || 0;
    const node = el('button', 'tab', icon(tab.icon), tab.label, count ? el('span', 'tab-count', String(count)) : null);
    node.type = 'button';
    if (count) node.setAttribute('aria-label', `${tab.label}, ${count} waiting`);
    if (tab.route === current) node.setAttribute('aria-current', 'page');
    node.addEventListener('click', () => go(tab.route));
    nav.append(node);
  }
  return nav;
}

function render(): void {
  if (!state.snapshot) return;
  if (!allowed(state.route)) state.route = 'home';
  const main = el('main', 'screen');
  main.id = 'main-content';
  const isTab = tabs().some(tab => tab.route === state.route);
  if (!isTab) {
    const back = el('button', 'back', icon('back'), 'Home');
    back.type = 'button';
    back.addEventListener('click', () => go('home'));
    main.append(el('div', 'screen-head', el('div', '', back, el('h1', 'screen-title', SCREENS[state.route].title))));
  } else {
    main.append(el('h1', 'visually-hidden', SCREENS[state.route].title));
  }
  SCREENS[state.route].draw(main);
  const skip = el('a', 'skip', 'Skip to content');
  skip.href = '#main-content';
  root.replaceChildren(el('div', 'shell', skip, topbar(),
    state.healthy ? null : el('div', 'stale-banner', 'No connection. What you see may be out of date, and changes are paused.'),
    main, tabbar()));
  const back = telegram()?.BackButton;
  if (back) { if (isTab) back.hide(); else back.show(); }
}

function redrawTopbar(): void {
  const current = root.querySelector('.topbar');
  if (current && state.snapshot) current.replaceWith(topbar());
}

// ---------- Data ----------

async function loadBrief(): Promise<void> {
  state.brief = can('timeline:approve') ? await api<Brief>('/api/brief') : undefined;
}

async function load(): Promise<void> {
  const epoch = state.sessionEpoch;
  const next = await api<Snapshot>('/api/snapshot');
  if (epoch !== state.sessionEpoch) return;
  state.snapshot = next;
  await loadBrief();
  state.lastRefresh = Date.now();
  state.healthy = true;
  render();
}

/** Fetch fresh state. Redraw only when something changed and the person is not mid-action. */
async function refresh(force = false): Promise<void> {
  const epoch = state.sessionEpoch;
  const previous = state.snapshot;
  if (!previous) return;
  try {
    const next = await api<Snapshot>('/api/snapshot');
    if (epoch !== state.sessionEpoch || next.me.id !== previous.me.id) return;
    const changed = next.wedding.state_version !== previous.wedding.state_version || next.wedding.timeline_version !== previous.wedding.timeline_version;
    state.snapshot = next;
    await loadBrief();
    state.healthy = true;
    state.lastRefresh = Date.now();
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName || '');
    if (force || (changed && !typing && !sheetOpen() && !isBusy())) render(); else redrawTopbar();
  } catch (error) {
    if (epoch !== state.sessionEpoch) return;
    state.healthy = false;
    redrawTopbar();
    if (force) throw error;
  }
}

// ---------- Sign-in ----------

function resetSession(): void {
  state.sessionEpoch++;
  state.brief = undefined;
  state.guestRows = [];
  state.guestQuery = '';
  state.guestDietary = false;
  state.route = 'home';
  closeAllSheets();
}

async function signInAsDemo(memberId: string): Promise<void> {
  resetSession();
  const data = await api<{csrf: string}>('/api/auth/demo', {member_id: memberId});
  state.csrf = data.csrf;
  await load();
}

function welcome(): void {
  const config = state.config!;
  const page = el('main', 'welcome', wordmark(), art('rings'), el('h1', '', 'The wedding day, in one place.'));
  if (config.demo) {
    page.append(el('p', '', 'This is a rehearsal with fictional guests. No real messages are sent. Choose who to be.'),
      list(...config.demo_members.map(member => row({title: member.name, meta: member.roles.map(roleWord).join(', '),
        onOpen: () => void signInAsDemo(member.id).catch(error => toast(errorText(error), true))}))));
  } else {
    page.append(el('p', '', 'Open LoveOnCue from the button in the Telegram chat, or use the personal link your coordinator sent you.'));
  }
  root.replaceChildren(page);
}

function accountSheet(): void {
  const s = snap();
  const config = state.config!;
  if (config.demo) {
    sheet({
      eyebrow: 'Rehearsal', title: 'Switch person', text: 'See the app as someone else. Fictional data only.',
      content: [
        list(...config.demo_members.map(member => row({
          title: member.name, meta: member.roles.map(roleWord).join(', '),
          end: member.id === s.me.id ? el('span', 'pill done', 'You') : null,
          onOpen: () => void signInAsDemo(member.id).catch(error => toast(errorText(error), true)),
        }))),
        isCoordinator() ? el('div', 'group', el('h3', 'group-title', 'Rehearsal clock'), el('div', 'card-actions',
          button('Move clock +5 min', async () => { await api('/api/demo/tick', {minutes: 5}); await refresh(true); toast('The rehearsal clock moved 5 minutes.'); }),
          button('Send due reminders', async () => {
            const result = await api<{processed: number}>('/api/demo/tick', {minutes: 0});
            await refresh(true);
            toast(`${result.processed} reminders handled. Nothing left this computer.`);
          }))) : null,
      ],
    });
    return;
  }
  sheet({
    eyebrow: s.me.roles.map(roleWord).join(', '), title: s.me.name,
    content: [note('You are signed in on this phone until you sign out or your session ends.')],
    actions: close => [button('Close', close), button('Sign out', async () => {
      await api('/api/logout', {});
      close();
      resetSession();
      state.snapshot = undefined;
      state.csrf = '';
      welcome();
    }, 'danger')],
  });
}

function applyTheme(): void {
  const scheme = telegram()?.colorScheme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = scheme;
}

async function boot(): Promise<void> {
  applyTheme();
  telegram()?.onEvent?.('themeChanged', applyTheme);
  telegram()?.BackButton?.onClick(() => go('home'));
  try {
    state.config = await api<Config>('/api/config');
    const invitation = new URLSearchParams(location.hash.slice(1)).get('invite');
    if (invitation) {
      history.replaceState(null, '', location.pathname);
      state.csrf = (await api<{csrf: string}>('/api/auth/invite', {token: invitation})).csrf;
      await load();
      return;
    }
    try {
      state.csrf = (await api<{csrf: string}>('/api/session')).csrf;
      await load();
      return;
    } catch { /* No session yet. */ }
    const webApp = telegram();
    if (webApp?.initData) {
      webApp.ready();
      state.csrf = (await api<{csrf: string}>('/api/auth/telegram', {init_data: webApp.initData})).csrf;
      webApp.expand();
      await load();
      return;
    }
    welcome();
  } catch (error) {
    root.replaceChildren(el('main', 'loading', wordmark(), el('p', 'error-text', errorText(error)), button('Try again', boot, 'primary')));
  }
}

setRenderer(render);
setAfterCommand(() => refresh(true));

const POLL_MS = 8000;          // Fresh enough for a live event; light on venue Wi-Fi.
const STALE_AFTER_MS = 15000;  // Refresh at once when the app comes back after this long.
let polling = false;
setInterval(() => {
  if (!state.snapshot || !state.csrf || polling || document.hidden) return;
  polling = true;
  void refresh(false).finally(() => { polling = false; });
}, POLL_MS);
window.addEventListener('online', () => { if (state.snapshot) void refresh(true).catch(error => toast(errorText(error), true)); });
window.addEventListener('offline', () => { state.healthy = false; if (state.snapshot) rerender(); });
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && state.snapshot && Date.now() - state.lastRefresh > STALE_AFTER_MS) void refresh(false);
});
void boot();
