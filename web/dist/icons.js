// LoveOnCue vector graphics, drawn for this product.
// Icons share one grid: 24 x 24, 1.75 stroke, round caps and joins. They are two-tone:
//   .i-fill   a soft fill behind the main shape (off in plain contexts)
//   .i-accent a brass detail stroke, .i-dot a brass detail fill
// The colours come from CSS (app.css, "Brand"), so icons follow the theme and dark mode.
// Every string here is a constant written by hand, never user data.
const ICON_ATTRIBUTES = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"';
const ICONS = {
    home: '<path class="i-fill" d="M4 10.5 12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19z"/>' +
        '<path d="M4 10.5 12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5H15v-5.5H9v5.5H5.5A1.5 1.5 0 0 1 4 19z"/><path class="i-accent" d="M9 20.5v-5.5h6v5.5"/>',
    // The cue line, the app's signature: a vertical line with cues on it.
    schedule: '<rect class="i-fill" x="3.5" y="3.5" width="17" height="17" rx="4" stroke="none"/><path d="M7.5 4.5v15"/>' +
        '<circle class="i-dot" cx="7.5" cy="8" r="1.9"/><circle cx="7.5" cy="12" r="1.6" fill="currentColor"/><circle cx="7.5" cy="16" r="1.6" fill="currentColor"/>' +
        '<path d="M11.5 8h7M11.5 12h5M11.5 16h6"/>',
    review: '<rect class="i-fill" x="4" y="4" width="16" height="16" rx="4.5"/><rect x="4" y="4" width="16" height="16" rx="4.5"/><path class="i-accent" d="m8.5 12.25 2.5 2.5 4.75-5"/>',
    crew: '<circle class="i-fill" cx="9" cy="8.5" r="3.25"/><circle cx="9" cy="8.5" r="3.25"/><path d="M3 19.5c.6-3.3 3-5.25 6-5.25s5.4 1.95 6 5.25"/>' +
        '<path class="i-accent" d="M15.5 5.4a3.25 3.25 0 0 1 0 6.2M17.5 14.6c1.8.7 3 2.4 3.5 4.9"/>',
    // A round banquet table with four curved chairs.
    guests: '<circle class="i-fill" cx="12" cy="12" r="4.75"/><circle cx="12" cy="12" r="4.75"/>' +
        '<path class="i-accent" stroke-width="2.25" d="M8.30 4.07A8.75 8.75 0 0 1 15.70 4.07M19.93 8.30A8.75 8.75 0 0 1 19.93 15.70M15.70 19.93A8.75 8.75 0 0 1 8.30 19.93M4.07 15.70A8.75 8.75 0 0 1 4.07 8.30"/>',
    jobs: '<rect class="i-fill" x="5" y="4.5" width="14" height="16.5" rx="2.5"/><rect x="5" y="4.5" width="14" height="16.5" rx="2.5"/>' +
        '<rect x="9" y="2.75" width="6" height="3.5" rx="1.25" fill="currentColor"/><path class="i-accent" d="m9 13.25 2 2 4-4.25"/>',
    pin: '<path class="i-fill" d="M12 21s6.5-5.6 6.5-11a6.5 6.5 0 0 0-13 0c0 5.4 6.5 11 6.5 11z"/><path d="M12 21s6.5-5.6 6.5-11a6.5 6.5 0 0 0-13 0c0 5.4 6.5 11 6.5 11z"/><circle class="i-dot" cx="12" cy="10" r="2.4"/>',
    book: '<path class="i-fill" d="M12 6.75C10.4 5.3 7.9 4.75 4 4.75v13c3.9 0 6.4.55 8 2 1.6-1.45 4.1-2 8-2v-13c-3.9 0-6.4.55-8 2z"/>' +
        '<path d="M12 6.75C10.4 5.3 7.9 4.75 4 4.75v13c3.9 0 6.4.55 8 2 1.6-1.45 4.1-2 8-2v-13c-3.9 0-6.4.55-8 2z"/><path class="i-accent" d="M12 6.75v13"/>',
    setup: '<path d="M4 6.5h8.5M17.5 6.5H20M4 12h2.5M11 12h9M4 17.5h10.5M19.5 17.5H20"/>' +
        '<circle class="i-fill" cx="15" cy="6.5" r="2.25"/><circle cx="15" cy="6.5" r="2.25"/><circle class="i-dot" cx="8.75" cy="12" r="2.4"/><circle class="i-fill" cx="17" cy="17.5" r="2.25"/><circle cx="17" cy="17.5" r="2.25"/>',
    log: '<path d="M10 6.5h10M10 12h10M10 17.5h7"/><circle class="i-dot" cx="5.5" cy="6.5" r="1.5"/><circle cx="5.5" cy="12" r="1.25" fill="currentColor"/><circle cx="5.5" cy="17.5" r="1.25" fill="currentColor"/>',
    alert: '<path class="i-fill" d="M10.3 4.4 2.7 17.8A2 2 0 0 0 4.4 20.8h15.2a2 2 0 0 0 1.7-3L13.7 4.4a2 2 0 0 0-3.4 0z"/>' +
        '<path d="M10.3 4.4 2.7 17.8A2 2 0 0 0 4.4 20.8h15.2a2 2 0 0 0 1.7-3L13.7 4.4a2 2 0 0 0-3.4 0z"/><path class="i-accent" d="M12 9.5v4.25M12 17.25h.01"/>',
    send: '<path class="i-fill" d="M4 10.25v3.5a1 1 0 0 0 1 1h2.25l7.75 4.5V4.75l-7.75 4.5H5a1 1 0 0 0-1 1z"/>' +
        '<path d="M4 10.25v3.5a1 1 0 0 0 1 1h2.25l7.75 4.5V4.75l-7.75 4.5H5a1 1 0 0 0-1 1z"/><path class="i-accent" d="M18.25 9a4 4 0 0 1 0 6"/><path d="M7.5 14.75l1.1 5h2.6l-1.1-5"/>',
    back: '<path d="m14.5 6-6 6 6 6"/>',
    chevron: '<path d="m9.5 6 6 6-6 6"/>',
    search: '<circle class="i-fill" cx="11" cy="11" r="6.5"/><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.4-4.4"/>',
    phone: '<path d="M5.5 4h3.25l1.75 4.5-2.25 1.4a10.5 10.5 0 0 0 5.85 5.85l1.4-2.25L20 15.25v3.25A1.75 1.75 0 0 1 18.25 20.25 15.75 15.75 0 0 1 3.75 5.75 1.75 1.75 0 0 1 5.5 4z"/>',
};
function fromMarkup(markup) {
    const template = document.createElement('template');
    template.innerHTML = markup;
    return template.content.firstElementChild;
}
export function icon(name, className = '') {
    const classes = className ? ` class="${className}"` : '';
    return fromMarkup(`<svg ${ICON_ATTRIBUTES} aria-hidden="true" focusable="false"${classes}>${ICONS[name]}</svg>`);
}
/** An icon in a brass-tinted tile chip. */
export function tileIcon(name) {
    const chip = document.createElement('span');
    chip.className = 'tile-icon';
    chip.append(icon(name));
    return chip;
}
/*
 * The mark, the same geometry as web/src/logo.svg without its background:
 * two linked rings (radius 10.5, centres 12 apart) and a sparkle for the cue.
 * The brass arc from 100 to 150 degrees is drawn over a shorter gap (108 to 142),
 * so the brass ring passes over the green ring at the bottom crossing.
 */
const MARK = '<circle class="ring-brass" cx="30" cy="26" r="10.5" stroke-width="3.5"/>' +
    '<circle class="ring-green" cx="18" cy="26" r="10.5" stroke-width="3.5"/>' +
    '<path class="ring-gap" d="M26.76 35.99A10.5 10.5 0 0 1 21.73 32.46" stroke-width="7.5" stroke-linecap="butt"/>' +
    '<path class="ring-brass" d="M28.18 36.34A10.5 10.5 0 0 1 20.91 31.25" stroke-width="3.5" stroke-linecap="butt"/>' +
    '<path class="spark" d="M40 4.5c.5 2.9 1.6 4 4.5 4.5-2.9.5-4 1.6-4.5 4.5-.5-2.9-1.6-4-4.5-4.5 2.9-.5 4-1.6 4.5-4.5z"/>';
export function brandMark(size = 32) {
    return fromMarkup(`<svg class="brand-mark" width="${size}" height="${size}" viewBox="0 0 48 48" fill="none" aria-hidden="true" focusable="false">${MARK}</svg>`);
}
/** Mark plus "Love on Cue" wordmark, with "on" in brass italic. */
export function wordmark(size = 30) {
    const node = document.createElement('span');
    node.className = 'wordmark';
    node.setAttribute('aria-label', 'LoveOnCue');
    const name = document.createElement('span');
    name.setAttribute('aria-hidden', 'true');
    const on = document.createElement('em');
    on.textContent = 'on';
    name.append('Love', on, 'Cue');
    node.append(brandMark(size), name);
    return node;
}
// Spot illustrations for empty and welcome states, 120 x 80, in the brand palette.
const ART = {
    // All clear: a blush disc, a ring with a brass check, and two sparkles.
    clear: '<circle class="art-wash" cx="60" cy="42" r="28"/><circle class="art-fill art-line" cx="60" cy="40" r="20"/>' +
        '<path class="art-accent-line" d="m51 40.5 6.5 6.5 12.5-13"/>' +
        '<path class="art-dot" d="M96 14c.6 3.6 2 5 5.6 5.6-3.6.6-5 2-5.6 5.6-.6-3.6-2-5-5.6-5.6 3.6-.6 5-2 5.6-5.6z"/>' +
        '<path class="art-dot" d="M24 52c.4 2.4 1.3 3.3 3.7 3.7-2.4.4-3.3 1.3-3.7 3.7-.4-2.4-1.3-3.3-3.7-3.7 2.4-.4 3.3-1.3 3.7-3.7z"/>',
    // A guest place card on a blush disc, and a brass magnifier.
    card: '<circle class="art-wash" cx="60" cy="44" r="30"/><path class="art-fill art-line" d="M30 60 44 30h36l14 30z"/><path class="art-line" d="M30 60h64"/>' +
        '<path class="art-line" d="M52 43h20M55 50h14"/><circle class="art-brass-wash" cx="88" cy="28" r="9"/><circle class="art-accent-line" cx="88" cy="28" r="9"/><path class="art-accent-line" d="m95 35 7 7"/>',
    // The cue line: a brass "now" line crossing three cues.
    cues: '<rect class="art-wash" x="22" y="8" width="76" height="64" rx="16"/><path class="art-line" d="M40 14v52"/><circle class="art-dot" cx="40" cy="24" r="4.5"/>' +
        '<circle class="art-fill art-line" cx="40" cy="44" r="4"/><circle class="art-fill art-line" cx="40" cy="60" r="4"/>' +
        '<path class="art-line" d="M52 24h32M52 44h24M52 60h28"/><path class="art-accent-line" d="M28 34h64"/>',
    // Welcome: the mark, large, on a blush disc.
    rings: '<circle class="art-wash" cx="60" cy="40" r="34"/><g transform="translate(24 3) scale(1.5)">' +
        MARK.replaceAll('class="spark"', 'class="art-dot"') + '</g>',
};
export function art(name) {
    return fromMarkup(`<svg class="art" viewBox="0 0 120 80" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ART[name]}</svg>`);
}
