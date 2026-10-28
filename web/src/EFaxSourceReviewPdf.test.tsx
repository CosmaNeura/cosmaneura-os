import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {EFaxSourceReviewPanel, type EFaxSourceReviewPanelProps} from './EFaxSourceReviewPanel';
import {openPrivatePdf, type PdfDocument, type PdfPage} from './private-pdf';
import {vendorSha256} from './vendor-contract';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import {efaxSourceApi} from './efax-inbound-source-api';
import {workspaceApi, WorkspaceApiError} from './workspace-api';

vi.mock('./private-pdf', async () => ({...await vi.importActual('./private-pdf'), openPrivatePdf: vi.fn()}));
vi.mock('./efax-inbound-source-api', async () => ({...await vi.importActual('./efax-inbound-source-api'), efaxSourceApi: {review: vi.fn(), resolve: vi.fn()}}));
vi.mock('./workspace-api', async () => ({...await vi.importActual('./workspace-api'), workspaceApi: {read: vi.fn()}}));
const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto');
const uuid = (n: number) => '00000000-0000-4000-8000-' + String(n).padStart(12, '0');
const bytes = new TextEncoder().encode('%PDF-1.4\nInvented test bytes; the renderer boundary is mocked.\n%%EOF');
const passage = 'Invented fax passage; uncertain details retained.';
let root: Root, host: HTMLDivElement, props: EFaxSourceReviewPanelProps, doc: PdfDocument;
const button = (label: string) => [...host.querySelectorAll('button')].find(value => value.textContent === label);
async function wait(check: () => void) {
  for (let i = 0; i < 250; i++) {
    let passed = false;
    await act(async () => {await new Promise(resolve => setTimeout(resolve, 2)); try {check(); passed = true;} catch {}});
    if (passed) return;
  }
  check();
}
async function render(next = props) {props = next; await act(async () => root.render(<EFaxSourceReviewPanel {...props}/>));}
async function mount() {await render(); await wait(() => expect(host.querySelector('textarea')).not.toBeNull());}
async function click(label: string) {
  await wait(() => expect(button(label)?.disabled, label).toBe(false));
  await act(async () => button(label)!.click());
}
async function enter() {
  await act(async () => {
    const area = host.querySelector('textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, passage);
    area.dispatchEvent(new Event('input', {bubbles: true}));
    const input = host.querySelector<HTMLInputElement>('[aria-label="Pages used"]')!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '1');
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}
const page = (): PdfPage => ({getViewport: ({scale}) => ({width: 600 * scale, height: 800 * scale}),
  render: () => ({promise: Promise.resolve(), cancel: vi.fn()}), verifyImages: async () => {},
  readText: vi.fn(async () => 'Optional literal page text'), cleanup: vi.fn()});
function intact() {
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe(passage);
  expect(host.querySelector<HTMLInputElement>('[aria-label="Pages used"]')?.value).toBe('1');
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].every(value => !value.checked)).toBe(true);
  expect(props.recovery!.persist).not.toHaveBeenCalled();
  expect(efaxSourceApi.review).not.toHaveBeenCalled();
  expect(efaxSourceApi.resolve).not.toHaveBeenCalled();
  expect(workspaceApi.read).not.toHaveBeenCalled();
  expect(props.onAskChief).not.toHaveBeenCalled();
}
beforeEach(async () => {
  vi.clearAllMocks(); vi.stubGlobal('crypto', webcrypto); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  // Node's TextEncoder/WebCrypto fixtures use the structured-clone realm, as in the encrypted mount tests.
  vi.stubGlobal('ArrayBuffer', structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal('Uint8Array', structuredClone(new Uint8Array(0)).constructor);
  expect(bytes).toBeInstanceOf(Uint8Array);
  props = {identity: {mode: 'clerk_jwt', getToken: async () => null},
    scope: {box_id: uuid(1), owner_id: uuid(2), workspace_id: uuid(3)},
    offered: {operation_id: uuid(4), document_sha256: await vendorSha256(bytes), pages: 1, label: 'Invented received fax'},
    visit: {id: uuid(3), label: 'Invented current visit', revision: 5},
    recovery: {authorize: vi.fn(async () => {}), load: vi.fn(async () => null), persist: vi.fn(async () => {}), denied: vi.fn()},
    onAuthenticationLost: vi.fn(), onAskChief: vi.fn(), onOpenDocument: vi.fn(async () => bytes),
    onRefreshDocument: vi.fn(async () => props.offered)};
  doc = {numPages: 1, getPage: vi.fn(async () => page()), destroy: vi.fn(async () => {})};
  vi.mocked(openPrivatePdf).mockResolvedValue(doc);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();});

it('opens the exact acquired bytes inline and closes without changing passage, pages or human checks', async () => {
  await mount(); await enter(); expect(props.onOpenDocument).not.toHaveBeenCalled();
  await click('Open original PDF');
  await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce());
  const [seen, metadata] = vi.mocked(openPrivatePdf).mock.calls[0];
  expect(seen).toEqual(bytes); expect(seen).not.toBe(bytes);
  expect(metadata).toEqual({artifact_id: props.offered.operation_id, sha256: props.offered.document_sha256, byte_length: bytes.length, media_type: 'application/pdf'});
  await wait(() => expect(host.querySelector('canvas')?.hidden).toBe(false));
  expect(host.querySelector('[aria-label="Original received fax PDF"]')).not.toBeNull();
  expect(host.querySelector('iframe, object, embed, a[download]')).toBeNull(); intact();
  await click('Close original PDF'); expect(doc.destroy).toHaveBeenCalledOnce(); expect(host.querySelector('canvas')).toBeNull(); intact();
  await click('Open original PDF'); await wait(() => expect(props.onOpenDocument).toHaveBeenCalledTimes(2));
});

it.each(['failed', 'wrong hash', 'not PDF', 'too large'])('keeps the passage and offers an explicit retry when original bytes are %s', async mode => {
  if (mode === 'failed') vi.mocked(props.onOpenDocument!).mockRejectedValueOnce(new Error('Invented connection failure'));
  else vi.mocked(props.onOpenDocument!).mockResolvedValueOnce(mode === 'too large' ? new Uint8Array(1_048_577) : new TextEncoder().encode(mode === 'not PDF' ? 'not a PDF' : '%PDF-different'));
  await mount(); await enter(); await click('Open original PDF');
  await wait(() => expect(host.textContent).toContain('The exact saved PDF could not be opened'));
  expect(openPrivatePdf).not.toHaveBeenCalled(); expect(button('Open original PDF')?.disabled).toBe(false); intact();
  await click('Open original PDF'); await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce()); intact();
});

it('conceals a checked private passage on current document unavailability and permits only an explicit private save before leaving', async () => {
  props = {...props, onOperationBusyChange: vi.fn()}; vi.mocked(props.onOpenDocument!).mockResolvedValueOnce(null);
  await mount(); await enter(); await act(async () => host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach(value => value.click()));
  await click('Open original PDF'); await wait(() => expect(host.querySelector('textarea')).toBeNull());
  expect(host.textContent).not.toContain(passage); expect(host.textContent).not.toContain('Invented current visit');
  expect(props.onAuthenticationLost).not.toHaveBeenCalled(); expect(props.recovery!.denied).not.toHaveBeenCalled();
  expect(openPrivatePdf).not.toHaveBeenCalled(); expect(props.recovery!.persist).not.toHaveBeenCalled();
  expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(true);
  await click('Save passage draft privately'); await wait(() => expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false));
  expect(props.recovery!.persist).toHaveBeenCalledWith(expect.objectContaining({passage, page_numbers: [1], pending: null, saved: null}));
  expect(host.querySelector('textarea')).toBeNull(); expect(efaxSourceApi.review).not.toHaveBeenCalled();
  await click('Check exact acquired PDF'); intactExceptPrivateSave();
});

function intactExceptPrivateSave() {
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe(passage);
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].every(value => !value.checked)).toBe(true);
  expect(efaxSourceApi.review).not.toHaveBeenCalled(); expect(props.onAskChief).not.toHaveBeenCalled();
}

it('keeps a parser failure explicit without implying the PDF or passage was reviewed', async () => {
  vi.mocked(openPrivatePdf).mockRejectedValueOnce(new Error('Unsupported or encrypted PDF'));
  await mount(); await enter(); await click('Open original PDF');
  await wait(() => expect(host.textContent).toContain('This PDF could not be opened for review'));
  expect(host.querySelector('canvas')?.hidden).toBe(true); intact();
  await click('Close original PDF'); intact();
});

it.each([401, 403, 404, 426])('conceals the passage and notifies existing account recovery after current PDF denial %s', async status => {
  const failure = new WorkspaceApiError(status); vi.mocked(props.onOpenDocument!).mockRejectedValueOnce(failure);
  await mount(); await enter(); await click('Open original PDF');
  await wait(() => expect(props.onAuthenticationLost).toHaveBeenCalledWith(failure));
  expect(props.recovery!.denied).toHaveBeenCalledWith(failure); expect(host.querySelector('textarea')).toBeNull();
  expect(host.textContent).not.toContain('Invented current visit'); expect(host.querySelector('canvas')).toBeNull();
  expect(openPrivatePdf).not.toHaveBeenCalled(); expect(props.recovery!.persist).not.toHaveBeenCalled();
});

it('does not send a late denial to a replacement owner after the PDF task is hidden', async () => {
  let reject!: (reason: unknown) => void;
  vi.mocked(props.onOpenDocument!).mockReturnValueOnce(new Promise((_, no) => {reject = no;}));
  await mount(); await enter(); await click('Open original PDF'); await render({...props, visible: false});
  await act(async () => reject(new WorkspaceApiError(403))); expect(props.onAuthenticationLost).not.toHaveBeenCalled();
  expect(props.recovery!.denied).not.toHaveBeenCalled(); await render({...props, visible: true}); intact();
});

it('aborts a closed request, waits for cleanup, then refuses old bytes before an explicit new open', async () => {
  let finish!: (value: Uint8Array) => void, signal!: AbortSignal;
  vi.mocked(props.onOpenDocument!).mockImplementationOnce(value => {signal = value; return new Promise(resolve => {finish = resolve;});});
  await mount(); await enter(); await click('Open original PDF'); await click('Close original PDF'); expect(signal.aborted).toBe(true);
  expect(button('Open original PDF')).toBeUndefined(); expect(host.textContent).toContain('Waiting for the current request to stop');
  await act(async () => finish(bytes)); expect(openPrivatePdf).not.toHaveBeenCalled();
  await click('Open original PDF'); await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce()); intact();
});

it('locks direct Back only during actual PDF loading and cancellation cleanup, not while the PDF is open', async () => {
  props = {...props, onOperationBusyChange: vi.fn()}; let finish!: (value: Uint8Array) => void;
  vi.mocked(props.onOpenDocument!).mockReturnValueOnce(new Promise(resolve => {finish = resolve;}));
  await mount(); await wait(() => expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false));
  await click('Open original PDF'); expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(true);
  await click('Close original PDF'); expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(true);
  await act(async () => finish(bytes)); await wait(() => expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false));
  expect(openPrivatePdf).not.toHaveBeenCalled(); await click('Open original PDF'); await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce());
  await wait(() => expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false)); expect(button('Close original PDF')).toBeDefined();
});

it('destroys visible PDF on retained task hide and does not automatically reopen on return', async () => {
  await mount(); await enter(); await click('Open original PDF'); await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce());
  await render({...props, visible: false}); expect(doc.destroy).toHaveBeenCalledOnce(); expect(host.querySelector('canvas')).toBeNull();
  await render({...props, visible: true}); expect(props.onOpenDocument).toHaveBeenCalledOnce(); intact();
});

it('refuses late PDF bytes across a hidden-then-visible episode', async () => {
  let finish!: (value: Uint8Array) => void, signal!: AbortSignal;
  vi.mocked(props.onOpenDocument!).mockImplementationOnce(value => {signal = value; return new Promise(resolve => {finish = resolve;});});
  await mount(); await enter(); await click('Open original PDF'); await render({...props, visible: false});
  expect(signal.aborted).toBe(true); await render({...props, visible: true}); await act(async () => finish(bytes));
  expect(openPrivatePdf).not.toHaveBeenCalled(); intact();
});

it.each(['identity', 'visit', 'offer', 'recovery'])('destroys the old PDF after %s replacement', async kind => {
  await mount(); await click('Open original PDF'); await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce());
  const changed = kind === 'identity' ? {...props, identity: {mode: 'clerk_jwt' as const, getToken: async () => null}} :
    kind === 'visit' ? {...props, visit: {...props.visit, revision: 6}} :
    kind === 'offer' ? {...props, offered: {...props.offered, operation_id: uuid(44)}} :
    {...props, recovery: {...props.recovery!, authorize: vi.fn(async () => {})}};
  await render(changed); expect(doc.destroy).toHaveBeenCalledOnce(); expect(host.querySelector('canvas')).toBeNull();
  expect(props.onOpenDocument).toHaveBeenCalledOnce();
});

it('clears the parser during native suspension and requires an explicit current document check before reopening', async () => {
  props.identity = {mode: 'clerk_jwt', getToken: async () => null, nativeSession: {revision: uuid(90), isCurrent: () => true}};
  await mount(); await enter(); await click('Open original PDF'); await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce());
  await act(async () => notifyNativeWorkspaceForeground(props.identity, false));
  expect(doc.destroy).toHaveBeenCalledOnce(); expect(host.querySelector('canvas')).toBeNull();
  await act(async () => notifyNativeWorkspaceForeground(props.identity, true)); expect(button('Open original PDF')).toBeUndefined();
  await click('Check exact acquired PDF'); expect(props.onOpenDocument).toHaveBeenCalledOnce(); intact();
});

it('clears the parser on pagehide and does not restore old bytes on pageshow', async () => {
  await mount(); await enter(); await click('Open original PDF'); await wait(() => expect(openPrivatePdf).toHaveBeenCalledOnce());
  await act(async () => window.dispatchEvent(new Event('pagehide'))); expect(doc.destroy).toHaveBeenCalledOnce(); expect(host.querySelector('canvas')).toBeNull();
  await act(async () => window.dispatchEvent(new Event('pageshow'))); expect(props.onOpenDocument).toHaveBeenCalledOnce(); intact();
});

it('aborts document loading on unmount and ignores late completion', async () => {
  let finish!: (value: Uint8Array) => void, signal!: AbortSignal;
  vi.mocked(props.onOpenDocument!).mockImplementationOnce(value => {signal = value; return new Promise(resolve => {finish = resolve;});});
  await mount(); await click('Open original PDF'); await act(async () => root.render(null)); expect(signal.aborted).toBe(true);
  await act(async () => finish(bytes)); expect(openPrivatePdf).not.toHaveBeenCalled(); expect(host.textContent).toBe('');
});

it('omits the unavailable open action when no exact-document callback exists', async () => {
  props = {...props, onOpenDocument: undefined}; await mount(); expect(button('Open original PDF')).toBeUndefined();
  expect(openPrivatePdf).not.toHaveBeenCalled();
});

async function invalidPages() {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>('[aria-label="Pages used"]')!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'not a page');
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

it.each(['empty', 'nonempty'])('escapes concealed invalid-page edits with an %s passage without saving or sharing', async value => {
  props = {...props, onOperationBusyChange: vi.fn()}; vi.mocked(props.onOpenDocument!).mockResolvedValueOnce(null);
  await mount(); if (value === 'nonempty') await enter(); await invalidPages(); await click('Open original PDF');
  await wait(() => expect(host.querySelector('textarea')).toBeNull()); expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(true);
  await click('Discard unsaved passage changes'); expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false);
  expect(props.recovery!.persist).not.toHaveBeenCalled(); expect(efaxSourceApi.review).not.toHaveBeenCalled();
  expect(efaxSourceApi.resolve).not.toHaveBeenCalled(); expect(props.onAskChief).not.toHaveBeenCalled();
  await click('Check exact acquired PDF'); expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('');
  expect(host.querySelector<HTMLInputElement>('[aria-label="Pages used"]')?.value).toBe('');
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].every(item => !item.checked)).toBe(true);
});

it('restores the last durable private draft when discarding concealed invalid-page edits', async () => {
  props = {...props, onOperationBusyChange: vi.fn()}; vi.mocked(props.onOpenDocument!).mockResolvedValueOnce(null);
  await mount(); await enter(); await click('Save passage draft privately');
  await wait(() => expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false));
  const persisted = structuredClone(vi.mocked(props.recovery!.persist).mock.calls[0][0]);
  await act(async () => {
    const area = host.querySelector('textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, passage + ' Unsaved change');
    area.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await invalidPages(); await click('Open original PDF'); await wait(() => expect(host.querySelector('textarea')).toBeNull());
  await click('Discard unsaved passage changes'); expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false);
  expect(props.recovery!.persist).toHaveBeenCalledOnce(); expect(vi.mocked(props.recovery!.persist).mock.calls[0][0]).toEqual(persisted);
  await click('Check exact acquired PDF'); expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe(passage);
  expect(host.querySelector<HTMLInputElement>('[aria-label="Pages used"]')?.value).toBe('1');
  expect(efaxSourceApi.review).not.toHaveBeenCalled(); expect(props.onAskChief).not.toHaveBeenCalled();
});

it('keeps concealed invalid-page discard locked during actual private persistence', async () => {
  props = {...props, onOperationBusyChange: vi.fn()}; vi.mocked(props.onOpenDocument!).mockResolvedValueOnce(null);
  await mount(); await enter(); await invalidPages(); await click('Open original PDF'); await wait(() => expect(host.querySelector('textarea')).toBeNull());
  let complete!: () => void; vi.mocked(props.recovery!.persist).mockReturnValueOnce(new Promise(resolve => {complete = resolve;}));
  await click('Save passage draft privately'); await wait(() => expect(props.recovery!.persist).toHaveBeenCalledOnce());
  expect(button('Discard unsaved passage changes')?.disabled).toBe(true); expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(true);
  await act(async () => complete()); await wait(() => expect(button('Discard unsaved passage changes')?.disabled).toBe(false));
  expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(true); await click('Discard unsaved passage changes');
  expect(props.onOperationBusyChange).toHaveBeenLastCalledWith(false); expect(props.recovery!.persist).toHaveBeenCalledOnce(); expect(efaxSourceApi.review).not.toHaveBeenCalled();
});
