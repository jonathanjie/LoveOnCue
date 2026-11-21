// Small DOM builders shared by every screen. All text goes in through textContent.
import { icon } from './icons.js';
export function el(tag, className = '', ...children) {
    const node = document.createElement(tag);
    if (className)
        node.className = className;
    for (const child of children) {
        if (child === null || child === undefined || child === false)
            continue;
        node.append(child);
    }
    return node;
}
export function errorText(error) {
    return error instanceof Error ? error.message : 'That did not work. Check your connection and try again.';
}
let toastTimer = 0;
export function toast(message, isError = false) {
    const node = document.querySelector('#toast');
    if (!node)
        return;
    node.textContent = message;
    node.className = isError ? 'show error' : 'show';
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { node.className = ''; }, isError ? 8000 : 4000);
}
let busyActions = 0;
/** True while a button's action is still running, so polling does not redraw under it. */
export function isBusy() { return busyActions > 0; }
/** A button that runs its action once at a time and reports failures in the toast. */
export function button(label, action, kind = '') {
    const node = el('button', `button ${kind}`.trim(), label);
    node.type = 'button';
    node.addEventListener('click', () => {
        if (node.disabled)
            return;
        node.disabled = true;
        busyActions++;
        Promise.resolve()
            .then(action)
            .catch(error => toast(errorText(error), true))
            .finally(() => { node.disabled = false; busyActions--; });
    });
    return node;
}
export function pill(label, tone = '') {
    return el('span', `pill ${tone}`.trim(), label);
}
export function empty(title, detail = '') {
    return el('div', 'empty', el('strong', '', title), detail);
}
export function groupTitle(title, count) {
    return el('h2', 'group-title', title, count === undefined ? null : el('span', 'count', String(count)));
}
export function note(message) { return el('p', 'note', message); }
/** A list row. With an action it is a button; otherwise plain content. Meta is one line unless wrapMeta. */
export function row(options) {
    const meta = options.meta ? el('div', options.wrapMeta ? 'row-meta wrap' : 'row-meta', options.meta) : null;
    const main = el('div', 'row-main', el('div', 'row-title', options.title), meta);
    const end = el('div', 'row-end', options.end || null, options.onOpen ? icon('chevron', 'chevron') : null);
    const tone = options.tone ? ` tone-${options.tone}` : '';
    if (!options.onOpen)
        return el('div', `row${tone}`, options.lead || null, main, end);
    const node = el('button', `row${tone}`, options.lead || null, main, end);
    node.type = 'button';
    node.addEventListener('click', options.onOpen);
    return node;
}
export function list(...rows) { return el('div', 'list', ...rows); }
export function segmented(options, current, choose, name) {
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
export function tile(options) {
    const classes = ['tile', options.small ? 'small' : '', options.tone ? `is-${options.tone}` : ''].filter(Boolean).join(' ');
    const node = el('button', classes, icon(options.icon), options.count === undefined ? null : el('span', 'tile-count', String(options.count)), el('span', 'tile-name', options.name), options.status ? el('span', 'tile-status', options.status) : null);
    node.type = 'button';
    node.addEventListener('click', options.onOpen);
    return node;
}
// ---------- Form fields ----------
export function field(label, value = '', options = {}) {
    const input = el('input');
    input.type = options.type || 'text';
    input.value = value;
    input.autocomplete = 'off';
    if (options.placeholder)
        input.placeholder = options.placeholder;
    const wrap = el('label', 'field', el('span', 'field-label', label), options.hint ? el('span', 'field-hint', options.hint) : null, input);
    return { wrap, input };
}
export function area(label, value = '', hint = '') {
    const input = el('textarea');
    input.value = value;
    input.rows = 3;
    input.maxLength = 2000; // The server accepts at most 2000 characters of free text.
    const wrap = el('label', 'field', el('span', 'field-label', label), hint ? el('span', 'field-hint', hint) : null, input);
    return { wrap, input };
}
export function choose(label, options, chosen = '') {
    const input = el('select');
    for (const option of options) {
        const node = el('option', '', option.name);
        node.value = option.id;
        input.append(node);
    }
    if (chosen)
        input.value = chosen;
    const wrap = el('label', 'field', el('span', 'field-label', label), input);
    return { wrap, input };
}
/** Pill-shaped radio or checkbox choices. Returns a reader for the chosen values. */
export function chips(label, options, multiple, chosen = []) {
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
    return { wrap, values: () => Array.from(box.querySelectorAll('input:checked'), input => input.value) };
}
// ---------- Bottom sheet ----------
let openSheets = 0;
/** True while a sheet is open; polling then leaves the screen alone. */
export function sheetOpen() { return openSheets > 0; }
/**
 * A modal bottom sheet. It replaces the browser's confirm() and prompt():
 * the person sees the full context and taps a labelled button.
 */
export function sheet(options) {
    const dialog = el('dialog', 'sheet');
    dialog.setAttribute('aria-label', options.title);
    const close = () => { if (dialog.open)
        dialog.close(); };
    const inner = el('div', 'sheet-inner', el('div', 'sheet-grip'), options.eyebrow ? el('div', `eyebrow ${options.eyebrowTone || ''}`.trim(), options.eyebrow) : null, el('h2', 'sheet-title', options.title), options.text ? el('p', 'sheet-text', options.text) : null, options.content ? el('div', 'sheet-content', ...options.content) : null);
    const actions = options.actions ? options.actions(close) : [button('Close', close)];
    if (actions.length)
        inner.append(el('div', 'sheet-actions', ...actions));
    dialog.append(inner);
    dialog.addEventListener('click', event => { if (event.target === dialog)
        close(); });
    dialog.addEventListener('close', () => { openSheets--; dialog.remove(); });
    document.body.append(dialog);
    openSheets++;
    dialog.showModal();
    return { dialog, close };
}
/** Close every open sheet, for example after signing in as someone else. */
export function closeAllSheets() {
    for (const dialog of Array.from(document.querySelectorAll('dialog.sheet')))
        dialog.close();
}
