// Small DOM builders shared by every screen. All text goes in through textContent.
import {icon, type IconName} from './icons.js';
import type {Tone} from './format.js';

type Child = Node | string | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', ...children: Child[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'That did not work. Check your connection and try again.';
}

let toastTimer = 0;
export function toast(message: string, isError = false): void {
  const node = document.querySelector<HTMLDivElement>('#toast');
  if (!node) return;
  node.textContent = message;
  node.className = isError ? 'show error' : 'show';
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { node.className = ''; }, isError ? 8000 : 4000);
}

let busyActions = 0;
/** True while a button's action is still running, so polling does not redraw under it. */
export function isBusy(): boolean { return busyActions > 0; }

/** A button that runs its action once at a time and reports failures in the toast. */
export function button(label: string, action: () => void | Promise<void>, kind = ''): HTMLButtonElement {
  const node = el('button', `button ${kind}`.trim(), label);
  node.type = 'button';
  node.addEventListener('click', () => {
    if (node.disabled) return;
    node.disabled = true;
    busyActions++;
    Promise.resolve()
      .then(action)
      .catch(error => toast(errorText(error), true))
      .finally(() => { node.disabled = false; busyActions--; });
  });
  return node;
}

export function pill(label: string, tone: Tone = ''): HTMLSpanElement {
  return el('span', `pill ${tone}`.trim(), label);
}

export function empty(title: string, detail = ''): HTMLDivElement {
  return el('div', 'empty', el('strong', '', title), detail);
}

export function groupTitle(title: string, count?: string | number): HTMLHeadingElement {
  return el('h2', 'group-title', title, count === undefined ? null : el('span', 'count', String(count)));
}

export function note(message: string): HTMLParagraphElement { return el('p', 'note', message); }

/** A list row. With an action it is a button; otherwise plain content. Meta is one line unless wrapMeta. */
export function row(options: {title: string; meta?: string; wrapMeta?: boolean; end?: Node | null; lead?: Node | null; tone?: string; onOpen?: () => void}): HTMLElement {
  const meta = options.meta ? el('div', options.wrapMeta ? 'row-meta wrap' : 'row-meta', options.meta) : null;
  const main = el('div', 'row-main', el('div', 'row-title', options.title), meta);
  const end = el('div', 'row-end', options.end || null, options.onOpen ? icon('chevron', 'chevron') : null);
  const tone = options.tone ? ` tone-${options.tone}` : '';
  if (!options.onOpen) return el('div', `row${tone}`, options.lead || null, main, end);
  const node = el('button', `row${tone}`, options.lead || null, main, end);
  node.type = 'button';
  node.addEventListener('click', options.onOpen);
  return node;
}

export function list(...rows: Node[]): HTMLDivElement { return el('div', 'list', ...rows); }

export function segmented<T extends string>(options: {value: T; label: string; count?: number}[], current: T, choose: (value: T) => void, name: string): HTMLDivElement {
  const bar = el('div', 'segmented');
  bar.setAttribute('role', 'group');
  bar.setAttribute('aria-label', name);
  for (const option of options) {
    const node = el('button', 'segment', option.label, option.count === undefined ? null : el('span', 'num', String(option.count)));
    node.type = 'button';
    node.setAttribute('aria-pressed', String(option.value === current));
    node.addEventListener('click', () => choose(option.value));
    bar.append(node);
  }
  return bar;
}

export function tile(options: {icon: IconName; name: string; status?: string; count?: string | number; tone?: '' | 'alert' | 'waiting'; small?: boolean; onOpen: () => void}): HTMLButtonElement {
  const classes = ['tile', options.small ? 'small' : '', options.tone ? `is-${options.tone}` : ''].filter(Boolean).join(' ');
  const node = el('button', classes,
    icon(options.icon),
    options.count === undefined ? null : el('span', 'tile-count', String(options.count)),
    el('span', 'tile-name', options.name),
    options.status ? el('span', 'tile-status', options.status) : null);
  node.type = 'button';
  node.addEventListener('click', options.onOpen);
  return node;
}

// ---------- Form fields ----------

export function field(label: string, value = '', options: {type?: string; hint?: string; placeholder?: string} = {}): {wrap: HTMLLabelElement; input: HTMLInputElement} {
  const input = el('input');
  input.type = options.type || 'text';
  input.value = value;
  input.autocomplete = 'off';
  if (options.placeholder) input.placeholder = options.placeholder;
  const wrap = el('label', 'field', el('span', 'field-label', label), options.hint ? el('span', 'field-hint', options.hint) : null, input);
  return {wrap, input};
}

export function area(label: string, value = '', hint = ''): {wrap: HTMLLabelElement; input: HTMLTextAreaElement} {
  const input = el('textarea');
  input.value = value;
  input.rows = 3;
  input.maxLength = 2000; // The server accepts at most 2000 characters of free text.
  const wrap = el('label', 'field', el('span', 'field-label', label), hint ? el('span', 'field-hint', hint) : null, input);
  return {wrap, input};
}

export function choose(label: string, options: {id: string; name: string}[], chosen = ''): {wrap: HTMLLabelElement; input: HTMLSelectElement} {
  const input = el('select');
  for (const option of options) {
    const node = el('option', '', option.name);
    node.value = option.id;
    input.append(node);
  }
  if (chosen) input.value = chosen;
  const wrap = el('label', 'field', el('span', 'field-label', label), input);
  return {wrap, input};
}

/** Pill-shaped radio or checkbox choices. Returns a reader for the chosen values. */
export function chips(label: string, options: {id: string; name: string}[], multiple: boolean, chosen: string[] = []): {wrap: HTMLFieldSetElement; values: () => string[]} {
  const name = `chips-${Math.random().toString(36).slice(2)}`;
  const box = el('div', 'choices');
  for (const option of options) {
    const input = el('input');
    input.type = multiple ? 'checkbox' : 'radio';
    input.name = name;
    input.value = option.id;
    input.checked = chosen.includes(option.id);
    box.append(el('label', 'choice', input, el('span', '', option.name)));
  }
  const wrap = el('fieldset', 'field', el('legend', 'field-label', label), box);
  return {wrap, values: () => Array.from(box.querySelectorAll<HTMLInputElement>('input:checked'), input => input.value)};
}

// ---------- Bottom sheet ----------

let openSheets = 0;
/** True while a sheet is open; polling then leaves the screen alone. */
export function sheetOpen(): boolean { return openSheets > 0; }

export type Sheet = {dialog: HTMLDialogElement; close: () => void};

/**
 * A modal bottom sheet. It replaces the browser's confirm() and prompt():
 * the person sees the full context and taps a labelled button.
 */
export function sheet(options: {eyebrow?: string; eyebrowTone?: string; title: string; text?: string; content?: Child[]; actions?: (close: () => void) => Node[]}): Sheet {
  const dialog = el('dialog', 'sheet');
  dialog.setAttribute('aria-label', options.title);
  const close = () => { if (dialog.open) dialog.close(); };
  const inner = el('div', 'sheet-inner',
    el('div', 'sheet-grip'),
    options.eyebrow ? el('div', `eyebrow ${options.eyebrowTone || ''}`.trim(), options.eyebrow) : null,
    el('h2', 'sheet-title', options.title),
    options.text ? el('p', 'sheet-text', options.text) : null,
    options.content ? el('div', 'sheet-content', ...options.content) : null);
  const actions = options.actions ? options.actions(close) : [button('Close', close)];
  if (actions.length) inner.append(el('div', 'sheet-actions', ...actions));
  dialog.append(inner);
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.addEventListener('close', () => { openSheets--; dialog.remove(); });
  document.body.append(dialog);
  openSheets++;
  dialog.showModal();
  return {dialog, close};
}

/** Close every open sheet, for example after signing in as someone else. */
export function closeAllSheets(): void {
  for (const dialog of Array.from(document.querySelectorAll<HTMLDialogElement>('dialog.sheet'))) dialog.close();
}
