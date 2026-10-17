// @vitest-environment-options {"url":"http://localhost:5173/"}
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterAll, afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.hoisted(() => {
    for (const [key, value] of Object.entries({ VITE_COSMAS_ENV: 'synth_os', VITE_WORKSPACE_ENABLED: 'true', VITE_WORKSPACE_AUTHENTICATED_ENABLED: 'true', VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED: 'true', VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED: 'true', VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED: 'true' }))
        vi.stubEnv(key, value);
});
import { EncounterWorkspace } from './EncounterWorkspace';
import { workspaceApi, type Workspace, type AuthenticatedWorkspaceIdentity } from './workspace-api';
import { DraftJournal, accountEditorAddress, editorAddress } from './draft-journal';
import { openDraftStore, privateDraftScope } from './draft-store';
import type { GoogleMessageRecoveryRecord } from './google-message-recovery';
import type { GoogleCalendarRecoveryRecord } from './google-calendar-recovery';
import type { ReviewableHandoff } from './handoff-review-api';
import { hasUnsavedWork } from './unsaved-work';
import { IDBFactory } from '../../clients/capture/node_modules/fake-indexeddb';
const { webcrypto } = await vi.importActual<{
    webcrypto: Crypto;
}>('node:crypto');
const util = 'node:util';
const { transferableAbortController } = await import(/* @vite-ignore */ util) as {
    transferableAbortController: () => AbortController;
};
const environment = (globalThis as typeof globalThis & {
    process?: {
        env: Record<string, string | undefined>;
    };
}).process?.env;
const configured = environment?.COSMAS_GOOGLE_FULL_LAB_URL;
const local = (value: string) => {
    const u = new URL(value);
    if (u.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname) || u.pathname !== '/' || u.search || u.hash || u.username || u.password)
        throw new Error('Only the owned synthetic loopback server is allowed.');
    return u.origin;
};
const base = configured ? local(configured) : null, calendar = environment?.COSMAS_GOOGLE_FULL_LAB_KIND === 'calendar', realFetch = globalThis.fetch.bind(globalThis);
type Wire = {
    path: string;
    method: string;
    key?: string;
    action?: string;
    status: number | null;
    lost?: boolean;
};
type Episode = {
    persona: string;
    round: number | string;
    workspace_id: string;
    steps: string[];
    wire: Wire[];
    passed: boolean;
    elapsed_ms: number;
    failure?: string;
};
type Packet = {
    workspace: Workspace;
    token: string;
    scope: {
        box_id: string;
        actor_id: string;
    };
};
type Counters = {
    provider_calls: number;
    model_rounds: number;
    workspace: Workspace;
};
type SourceRecord = GoogleMessageRecoveryRecord | GoogleCalendarRecoveryRecord;
const trials: Episode[] = [], recoveries: Episode[] = [], transports = new Set<Promise<Response>>();
let root: Root | undefined, host: HTMLDivElement, idb: IDBFactory, identity: AuthenticatedWorkspaceIdentity, packet: Packet, active: Episode | undefined, namespace: string, terminal: string | undefined, loseSuffix: string | undefined, revoked: Counters | undefined;
const sourceEditor = () => calendar ? 'google-calendar' as const : 'google-messages' as const;
const exactSelector = () => calendar ? '[aria-label="Exact selected calendar summary"]' : '[aria-label="Complete selected email"]';
const sourceSuffix = () => calendar ? '/google-calendar/review' : '/google-messages/review';
const saveLabel = () => calendar ? 'Save calendar summary to visit' : 'Save reviewed email for this visit';
const askLabel = () => calendar ? 'Ask Chief about this calendar summary' : 'Ask Chief about this email';
const sourceRestore = () => calendar ? 'Restore saved calendar work' : 'Restore saved email work';
const note = (w: Workspace) => JSON.stringify(w.note ?? null);
const visible = (element: Element) => !element.closest('[hidden]');
function button(label: string, region: ParentNode = host) { const found = [...region.querySelectorAll<HTMLButtonElement>('button')].find(b => visible(b) && (b.textContent?.trim() === label || b.textContent?.replace(/^📄\s*/u, '').trim() === label || b.getAttribute('aria-label') === label || [...b.querySelectorAll('strong')].some(e => e.textContent?.trim() === label))); expect(found, label).toBeTruthy(); return found!; }
async function wait(check: () => void | Promise<void>) {
    const until = performance.now() + 12000;
    while (performance.now() < until) {
        let done = false;
        await act(async () => {
            await new Promise(r => setTimeout(r, 10));
            try {
                await check();
                done = true;
            }
            catch { }
        });
        if (done)
            return;
    }
    await check();
}
async function click(label: string, region: ParentNode = host) { await wait(() => expect(button(label, region).disabled, label).toBe(false)); await act(async () => button(label, region).click()); }
async function text(selector: string, value: string) { await wait(() => expect(host.querySelector(selector)).toBeTruthy()); const q = host.querySelector<HTMLTextAreaElement>(selector)!; await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(q, value); q.dispatchEvent(new Event('input', { bubbles: true })); }); }
async function checkSource() {
    const selector = calendar ? '.google-calendar-checks input' : '.google-message-check input';
    await wait(() => expect(host.querySelector<HTMLInputElement>(selector)?.disabled).toBe(false));
    for (const q of host.querySelectorAll<HTMLInputElement>(selector)) {
        await wait(() => expect(q.disabled).toBe(false));
        if (!q.checked)
            await act(async () => q.click());
        await wait(() => expect(q.checked).toBe(true));
    }
}
async function inspect(path: 'inspect' | 'revoke' = 'inspect'): Promise<Counters> { const r = path === 'revoke' ? await realFetch(base + '/lab/revoke', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_id: packet.workspace.id }), cache: 'no-store', credentials: 'omit', redirect: 'error' }) : await realFetch(base + '/lab/inspect?workspace_id=' + packet.workspace.id, { cache: 'no-store', credentials: 'omit', redirect: 'error' }); expect(r.status, await r.clone().text()).toBe(200); return r.json(); }
async function read() { const w = await workspaceApi.read(identity, packet.workspace.id); expect(note(w)).toBe(note(packet.workspace)); if (calendar) {
    const mail = w.entries.filter(e => e.kind === 'google_message');
    expect(mail.map(e => e.id)).toEqual(packet.workspace.entries.filter(e => e.kind === 'google_message').map(e => e.id));
    if (revoked) {
        expect(mail.every(e => e.content === '' && e.google_source_state === 'unavailable')).toBe(true);
    }
    else {
        expect(mail.map(e => e.content)).toEqual(packet.workspace.entries.filter(e => e.kind === 'google_message').map(e => e.content));
    }
} return w; }
async function refresh() { await click('Refresh encounter'); await wait(() => expect(button('Refresh encounter').disabled).toBe(false)); return read(); }
async function mount() { root = createRoot(host); await act(async () => root!.render(<EncounterWorkspace authenticated={identity}/>)); await click('Visits and notes'); await wait(() => expect([...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b => b.textContent?.includes(packet.workspace.label))).toBe(true)); await act(async () => [...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b => b.textContent?.includes(packet.workspace.label))!.click()); await wait(() => expect(host.querySelector('#team-notebook')).toBeTruthy()); }
async function open(persona: string, round: string) { const r = await realFetch(`${base}/lab/case?persona=${persona}&round=${round}`, { cache: 'no-store', credentials: 'omit', redirect: 'error' }); expect(r.status, await r.clone().text()).toBe(200); packet = await r.json(); identity = { mode: 'clerk_jwt', getToken: async () => packet.token }; const team = await workspaceApi.team(identity); namespace = await privateDraftScope(team.recovery_scope!, base!, webcrypto); await mount(); }
async function settings() { await click('Team settings'); await click('Connections', host.querySelector('.settings-hub')!); await click('Google email & calendar', host.querySelector('.settings-hub')!); await wait(() => expect(host.querySelector('.google-connection')?.textContent).toContain(revoked ? 'Connect your Google account to continue.' : 'Google connected.')); await click(calendar ? '📅 Work with calendar' : 'Work with email'); await wait(() => expect(host.querySelector(calendar ? '.google-calendar-panel' : '.google-message-panel')?.textContent).toMatch(/Check (?:calendar|email) access|Restore saved (?:calendar|email) work/)); }
async function reopen() { await act(async () => root!.unmount()); root = undefined; await mount(); }
async function journalRecord(address: string) {
    const j = new DraftJournal(await openDraftStore({ scope: namespace, native: false, indexedDB: idb, crypto: webcrypto }));
    try {
        return await j.load(address);
    }
    finally {
        j.close();
    }
}
async function sourceRecord() { const r = await journalRecord(accountEditorAddress(sourceEditor())); expect(r?.kind).toBe('account-editor'); return r?.kind === 'account-editor' ? r.data as SourceRecord : null; }
async function encrypted() {
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const q = idb.open(`cosmas-private-drafts:v1:${namespace}`); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
    try {
        const tx = db.transaction(['sealed-drafts', 'metadata'], 'readonly');
        const rows = await new Promise<unknown[]>((resolve, reject) => { const q = tx.objectStore('sealed-drafts').getAll(); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
        expect(rows.length).toBeGreaterThan(0);
        expect(JSON.stringify(rows)).not.toContain('Invented visit follow-up');
        expect(JSON.stringify(rows)).not.toContain('sender@example.invalid');
        expect(JSON.stringify(rows)).not.toContain('identify an owner');
        const key = await new Promise<CryptoKey>((resolve, reject) => { const q = tx.objectStore('metadata').get('draft-key-v1'); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
        expect(key.extractable).toBe(false);
        expect(key.algorithm.name).toBe('AES-GCM');
    }
    finally {
        db.close();
    }
}
async function selectSource() {
    await click(calendar ? 'Check calendar access' : 'Check email access');
    if (calendar) {
        await click('Load next 7 days');
        await wait(() => expect(host.querySelector<HTMLButtonElement>('[data-calendar-event="invented-timed"]')?.disabled).toBe(false));
        await act(async () => host.querySelector<HTMLButtonElement>('[data-calendar-event="invented-timed"]')!.click());
        await click('Use current visit');
        await checkSource();
    }
    else {
        await click('Select email');
        await wait(() => expect(host.querySelector<HTMLButtonElement>('.google-message-list button')?.disabled).toBe(false));
        await act(async () => host.querySelector<HTMLButtonElement>('.google-message-list button')!.click());
        await click('Read full email');
        await click('Use for current visit');
        await checkSource();
    }
    await wait(() => expect(host.querySelector(exactSelector())).toBeTruthy());
}
async function saveSource() { const content = host.querySelector(exactSelector())!.textContent!; await click(saveLabel()); await wait(() => expect(host.textContent).toContain(calendar ? 'Calendar source saved' : 'Email source saved')); const w = await read(); const r = (await sourceRecord())!; const entry = w.entries.find(e => e.id === r.saved!.entry_id)!; expect(entry.content).toBe(content); expect(entry.kind).toBe(calendar ? 'google_calendar' : 'google_message'); return { content, entry }; }
async function askChief() { const before = await inspect(); await click(askLabel()); await wait(() => expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toContain(calendar ? 'human-selected calendar summary' : 'human-selected email source')); expect(host.querySelector('.settings-hub')!.hasAttribute('hidden')).toBe(true); const prepared = await inspect(); expect(prepared.model_rounds).toBe(before.model_rounds); await text('#team-question', host.querySelector<HTMLTextAreaElement>('#team-question')!.value + ' Ask Scribe for a private follow-up draft; preserve unknown heart history, missing DOB and trial eligibility.'); await click('Send message'); await wait(() => expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toBe('')); }
async function workers(handoff?: string) { const r = await realFetch(base + '/lab/work', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_id: packet.workspace.id, ...(handoff ? { handoff_id: handoff } : {}) }), cache: 'no-store', credentials: 'omit', redirect: 'error' }); expect(r.status, await r.clone().text()).toBe(200); await refresh(); return read(); }
async function review(handoff: ReviewableHandoff, masked = false) {
    const earlier = host.querySelector<HTMLDetailsElement>('.team-earlier-tasks');
    if (earlier)
        earlier.open = true;
    await click(masked ? `Check saved ${handoff.recipient_name} review` : `Review ${handoff.recipient_name} result`);
    await wait(() => expect(host.querySelector(masked ? '.handoff-review' : '[aria-label="Complete saved draft"]')).toBeTruthy());
}
async function revisionAccept(lost = false) { await askChief(); let w = await workers(); const first = w.handoffs!.find(h => h.status === 'completed')! as ReviewableHandoff; await review(first); await click('Request changes'); const feedback = `${active!.persona}: identify an owner and due date, keeping missing heart history and trial eligibility unconfirmed.`; await text('.handoff-review textarea', feedback); await click('Save change request'); await wait(() => expect(button('Prepare revised draft').disabled).toBe(false)); w = await read(); expect((w.handoffs!.find(h => h.id === first.id)! as ReviewableHandoff).review).toMatchObject({ decision: 'changes_requested', feedback, result_sha256: first.result_sha256 }); await click('Prepare revised draft'); await wait(() => expect(host.textContent).not.toContain('Saving revised assignment…')); w = await read(); const revision = w.handoffs!.find(h => (h as ReviewableHandoff).revision_request?.parent_handoff_id === first.id)! as ReviewableHandoff; expect(revision).toBeTruthy(); w = await workers(revision.id); const final = w.handoffs!.find(h => h.id === revision.id)! as ReviewableHandoff; expect(final.status).toBe('completed'); await wait(() => expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toContain(feedback)); const content = host.querySelector('[aria-label="Complete saved draft"]')!.textContent!; if (lost) {
    loseSuffix = `/handoffs/${final.id}/review`;
    await click('Accept draft for next work');
    await wait(() => expect(revoked).toBeTruthy());
    await wait(() => expect(host.textContent).toContain('Review save unconfirmed'));
    return { accepted: final, content };
} await click('Accept draft for next work'); await wait(() => expect(host.querySelector('.handoff-review')?.textContent).toContain('Draft accepted')); w = await read(); const accepted = w.handoffs!.find(h => h.id === final.id)! as ReviewableHandoff; expect(accepted.review).toMatchObject({ decision: 'accepted', attempt_id: final.attempt_id, result_entry_id: final.result_entry_id, result_sha256: final.result_sha256 }); await click('Close draft review'); return { accepted, content }; }
beforeEach(() => {window.history.replaceState(null,'',window.location.pathname+window.location.search);
    if (!base)
        return;
    if (terminal)
        throw new Error('Previous full Google episode failed; no further synthetic case admitted: ' + terminal);
    const native = transferableAbortController();
    vi.stubGlobal('AbortController', native.constructor);
    vi.stubGlobal('AbortSignal', native.signal.constructor);
    vi.stubGlobal('crypto', webcrypto);
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.stubEnv('VITE_API_BASE', base);
    vi.stubGlobal('ArrayBuffer', structuredClone(new ArrayBuffer(0)).constructor);
    vi.stubGlobal('Uint8Array', structuredClone(new Uint8Array(0)).constructor);
    idb = new IDBFactory();
    vi.stubGlobal('indexedDB', idb);
    host = document.createElement('div');
    document.body.append(host);
    loseSuffix = undefined;
    revoked = undefined;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
        const u = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        if (u.origin !== base)
            throw new Error('Only the owned loopback API may be requested.');
        const item: Wire = { path: u.pathname, method: init?.method ?? 'GET', status: null };
        if (typeof init?.body === 'string') {
            try {
                const body = JSON.parse(init.body);
                item.key = body.idempotency_key;
                item.action = body.action;
            }
            catch { }
        }
        active?.wire.push(item);
        const work = realFetch(input, init);
        transports.add(work);
        try {
            const r = await work;
            item.status = r.status;
            if (loseSuffix && u.pathname.endsWith(loseSuffix) && item.method === 'POST' && r.status === 200) {
                loseSuffix = undefined;
                await r.arrayBuffer();
                revoked = await inspect('revoke');
                item.lost = true;
                throw new TypeError('Invented lost reply after actual commit and source revocation');
            }
            return r;
        }
        finally {
            transports.delete(work);
        }
    });
});
afterEach(async () => {
    try {
        await Promise.allSettled([...transports]);
        if (root)
            await act(async () => root!.unmount());
    }
    finally {
        root = undefined;
        host?.remove();
        active = undefined;
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    }
});
it.skipIf(!base).each([{ persona: 'physician', round: 1 }, { persona: 'nurse_practitioner', round: 1 }, { persona: 'physician_assistant', round: 1 }, { persona: 'physician', round: 2 }, { persona: 'nurse_practitioner', round: 2 }, { persona: 'physician_assistant', round: 2 }])('$persona round $round completes full settings source → Chief → revised specialist acceptance and encrypted reopen', async ({ persona, round }) => {
    const started = performance.now(), ep: Episode = { persona, round, workspace_id: '', steps: [], wire: [], passed: false, elapsed_ms: 0 };
    active = ep;
    trials.push(ep);
    try {
        await open(persona, String(round));
        ep.workspace_id = packet.workspace.id;
        await settings();
        ep.steps.push('actual_encounter_selection_settings_google_connection_no_content_read');
        await selectSource();
        const selected = host.querySelector(exactSelector())!.textContent!;
        const retained = structuredClone(await sourceRecord()), before = await inspect();
        await encrypted();
        await reopen();
        await settings();
        await click(sourceRestore());
        await click(calendar ? 'Check calendar access' : 'Check email access');
        await wait(() => expect(host.querySelector(exactSelector())?.textContent).toBe(selected));
        expect(await sourceRecord()).toEqual(retained);
        expect((await inspect()).provider_calls).toBe(before.provider_calls);
        ep.steps.push('fresh_parent_journal_restore_exact_selected_source_without_provider_repeat');
        await click(calendar ? 'Check calendar access' : 'Check email access');
        await click(calendar ? 'Use current visit' : 'Use for current visit');
        await checkSource();
        const saved = await saveSource();
        const final = await revisionAccept();
        ep.steps.push('actual_chief_message_tool_worker_requested_revision_exact_human_acceptance');
        await encrypted();
        const prior = await inspect();
        await reopen();
        const reread = await read();
        expect(reread.entries.find(e => e.id === saved.entry.id)?.content).toBe(saved.content);
        expect((reread.handoffs!.find(h => h.id === final.accepted.id)! as ReviewableHandoff).review).toEqual(final.accepted.review);
        await review(final.accepted);
        await wait(() => expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toBe(final.content));
        expect(host.querySelector('.handoff-review')?.textContent).toContain('Draft accepted');
        await click('Close draft review');
        expect((await inspect()).provider_calls).toBe(prior.provider_calls);
        expect((await inspect()).model_rounds).toBe(prior.model_rounds);
        await wait(() => expect(hasUnsavedWork()).toBe(false));
        ep.steps.push('fresh_full_encounter_reopened_exact_accepted_specialist_without_dispatch');
        ep.passed = true;
    }
    catch (e) {
        ep.failure = String(e) + '\nDOM: ' + host.textContent;
        terminal = ep.failure.split('\n')[0];
        throw e;
    }
    finally {
        ep.elapsed_ms = Math.round(performance.now() - started);
    }
}, 60000);
it.skipIf(!base).each(['masked_source', 'masked_handoff', 'masked_revised_handoff', 'revoked_accepted'] as const)('%s recovers or withholds full-interface work after source revocation without repeat dispatch', async (kind) => {
    const started = performance.now(), ep: Episode = { persona: 'physician', round: kind, workspace_id: '', steps: [], wire: [], passed: false, elapsed_ms: 0 };
    active = ep;
    recoveries.push(ep);
    try {
        await open('physician', kind);
        ep.workspace_id = packet.workspace.id;
        await settings();
        await selectSource();
        if (kind === 'masked_source') {
            loseSuffix = sourceSuffix();
            await click(saveLabel());
            await wait(async () => expect((await sourceRecord())?.pending?.kind).toBe('review'));
            await wait(() => expect(revoked).toBeTruthy());
            await wait(() => expect(button(calendar ? 'Retry exact calendar source save' : 'Retry exact source save').disabled).toBe(false));
            const original = structuredClone((await sourceRecord())!.pending);
            await encrypted();
            await reopen();
            await settings();
            await click(sourceRestore());
            expect((await sourceRecord())!.pending).toEqual(original);
            await click(calendar ? 'Retry exact calendar source save' : 'Retry exact source save');
            await wait(() => expect(host.textContent).toContain(calendar ? 'exact calendar source save is confirmed' : 'exact email source save is confirmed'));
            expect((await sourceRecord())!.saved?.source_withheld).toBe(true);
            expect((await sourceRecord())!.pending).toBeNull();
            expect(host.querySelector(exactSelector())).toBeNull();
            const repeated = ep.wire.filter(w => w.path.endsWith(sourceSuffix()));
            expect(repeated).toHaveLength(2);
            expect(repeated[1].key).toBe(repeated[0].key);
            ep.steps.push('encrypted_original_source_command_fresh_parent_restore_same_key_masked_commit');
        }
        else if (kind === 'masked_handoff' || kind === 'masked_revised_handoff') {
            await saveSource();
            let h: ReviewableHandoff;
            if (kind === 'masked_revised_handoff') {
                h = (await revisionAccept(true)).accepted;
            }
            else {
                await askChief();
                const w = await workers();
                h = w.handoffs!.find(h => h.status === 'completed')! as ReviewableHandoff;
                await review(h);
                await click('Request changes');
                await text('.handoff-review textarea', 'identify an owner and due date; preserve unknown heart history');
                loseSuffix = `/handoffs/${h.id}/review`;
                await click('Save change request');
                await wait(() => expect(revoked).toBeTruthy());
                await wait(() => expect(host.textContent).toContain('Review save unconfirmed'));
            }
            const local = await journalRecord(editorAddress(packet.workspace.id, `handoff-review:${h.id}`));
            expect(local?.pending).toBeTruthy();
            await encrypted();
            await reopen();
            await review(h, true);
            await click('Restore handoff review draft');
            await wait(() => expect(button('Check saved review status').disabled).toBe(false));
            expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();
            expect(host.textContent).not.toContain('identify an owner and due date; preserve');
            await click('Check saved review status');
            await click('Retry same review save');
            await wait(() => expect(host.textContent).toContain('exact saved review is confirmed'));
            const repeated = ep.wire.filter(w => w.path.endsWith(`/handoffs/${h.id}/review`));
            expect(repeated).toHaveLength(2);
            expect(repeated[1].key).toBe(repeated[0].key);
            expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();
            expect([...host.querySelectorAll<HTMLButtonElement>('button')].filter(b => visible(b) && b.textContent === 'Accept draft for next work').every(b => b.disabled)).toBe(true);
            ep.steps.push('actual_parent_handoff_editor_ciphertext_fresh_remount_same_review_key_source_withheld');
        }
        else {
            await saveSource();
            const final = await revisionAccept();
            revoked = await inspect('revoke');
            await reopen();
            const masked = await read();
            expect(masked.entries.filter(e => e.kind === (calendar ? 'google_calendar' : 'google_message')).every(e => !e.content)).toBe(true);
            const h = masked.handoffs!.find(h => h.id === final.accepted.id)! as ReviewableHandoff;
            expect(h.review_status).toBe('stale');
            await review(h, true);
            expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();
            expect(host.textContent).not.toContain(final.content);
            expect([...host.querySelectorAll<HTMLButtonElement>('button')].filter(b => visible(b) && b.textContent === 'Accept draft for next work').every(b => b.disabled)).toBe(true);
            ep.steps.push('fresh_full_encounter_masks_previously_accepted_source_and_draft_after_revocation');
        }
        const after = await inspect();
        expect(after.provider_calls).toBe(revoked!.provider_calls);
        expect(after.model_rounds).toBe(revoked!.model_rounds);
        expect(note(after.workspace)).toBe(note(packet.workspace));
        ep.steps.push('provider_and_model_counters_unchanged_after_revocation');
        ep.passed = true;
    }
    catch (e) {
        ep.failure = String(e) + '\nDOM: ' + host.textContent;
        terminal = ep.failure.split('\n')[0];
        throw e;
    }
    finally {
        ep.elapsed_ms = Math.round(performance.now() - started);
    }
}, 60000);
afterAll(async () => {
    if (!base || !environment?.COSMAS_GOOGLE_FULL_LAB_REPORT)
        return;
    const mod = 'node:fs/promises';
    const fs = await import(/* @vite-ignore */ mod) as {
        writeFile: (p: string, v: string) => Promise<void>;
    };
    await fs.writeFile(environment.COSMAS_GOOGLE_FULL_LAB_REPORT, JSON.stringify({ schema: 'cosmabot.google-full-encounter-signed-server-lab.v1', source_kind: calendar ? 'calendar' : 'email', synthetic_only: true, actual_EncounterWorkspace_SettingsHub_GoogleConnectionPanel_source_mounts: true, parent_DraftJournal_actual_AES_GCM_IndexedDB: true, full_handoff_editor_recovery: true, nonextractable_key: true, episodes: trials, recovery_episodes: recoveries, total: trials.length + recoveries.length, completed: [...trials, ...recoveries].filter(e => e.passed).length, boundary: 'Actual product components/APIs/parsers/signed local identity verifier/PostgreSQL/tool worker. fake IndexedDB replaces browser database platform only; AES-GCM journal source unchanged. Invented Google content/grants and model MockTransport. No live account/provider/model/cloud, native device or unscripted clinician usability.' }, null, 2) + '\n');
});
