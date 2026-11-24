// Same-origin API client. The session cookie is HttpOnly; writes also send the CSRF token.
import { state } from './state.js';
export async function api(path, body) {
    const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf, 'X-WeddingOps-Client': '1' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json();
    if (!response.ok) {
        const failure = data;
        throw new Error(failure.error?.message || `Request failed (${response.status})`);
    }
    return data;
}
function requestId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}
let afterCommand = async () => { };
/** The app refreshes its snapshot after every recorded command. */
export function setAfterCommand(next) { afterCommand = next; }
/**
 * Send one typed command. The server checks permission, version and idempotency.
 * A network failure is retried once with the same request ID, so it cannot apply twice.
 */
export async function command(payload) {
    if (!state.healthy)
        throw new Error('The connection dropped. Wait until it says Live again, then try again.');
    const request = { command: payload, request_id: requestId() };
    try {
        await api('/api/commands', request);
    }
    catch (error) {
        if (!(error instanceof TypeError))
            throw error;
        await api('/api/commands', request);
    }
    await afterCommand();
}
