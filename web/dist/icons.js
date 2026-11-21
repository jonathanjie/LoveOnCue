// Static, hand-drawn line icons (24 x 24). The strings are constants, never user data.
const stroke = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
const PATHS = {
    home: '<path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"/>',
    schedule: '<path d="M7 4v16M7 7h11M7 12h8M7 17h10"/><circle cx="7" cy="12" r="1.5" fill="currentColor"/>',
    review: '<path d="M4 13l4 4L20 5"/><path d="M4 7h7"/>',
    crew: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.5 3.4-5.5 6.5-5.5s5.7 2 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c1.8.8 3 2.6 3.5 5.2"/>',
    guests: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    jobs: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 12l2 2 4-4"/>',
    pin: '<path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    book: '<path d="M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 1-4-4z"/><path d="M5 16a4 4 0 0 1 4-4h10"/>',
    setup: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
    log: '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17h.01"/>',
    send: '<path d="M3 10v4l11 5V5z"/><path d="M14 8a4 4 0 0 1 0 8M6 14l1 6h3l-1-5"/>',
    back: '<path d="M15 6l-6 6 6 6"/>',
    chevron: '<path d="M9 6l6 6-6 6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
};
export function icon(name, className = '') {
    const template = document.createElement('template');
    template.innerHTML = `<svg viewBox="0 0 24 24" ${stroke} aria-hidden="true" focusable="false"${className ? ` class="${className}"` : ''}>${PATHS[name]}</svg>`;
    return template.content.firstElementChild;
}
