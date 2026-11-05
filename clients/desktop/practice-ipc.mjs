/**
 * IPC for CosmasDesktopPractice. Mirrors auth-ipc: exact document URL, no credential channel.
 */

import {isPackagedWorkspaceDocument} from './workspace-document.mjs';

export const PRACTICE_CHANNELS = Object.freeze({
  capabilities: 'cosmas:desktop-practice:capabilities:v1',
  accountStatus: 'cosmas:desktop-practice:account-status:v1',
  beginAccountSignIn: 'cosmas:desktop-practice:begin-sign-in:v1',
  accountToken: 'cosmas:desktop-practice:account-token:v1',
  enrollmentRequest: 'cosmas:desktop-practice:enrollment-request:v1',
  openCheckout: 'cosmas:desktop-practice:open-checkout:v1',
  openEnrollmentDestination: 'cosmas:desktop-practice:open-destination:v1',
  activatePracticeOrganization: 'cosmas:desktop-practice:activate-org:v1',
  activateRegisteredPractice: 'cosmas:desktop-practice:activate-registered:v1',
  returnToBeta: 'cosmas:desktop-practice:return-to-beta:v1',
  signOut: 'cosmas:desktop-practice:sign-out:v1',
  changed: 'cosmas:desktop-practice:account-changed:v1',
});

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const unavailable = () => new Error('Desktop practice connection unavailable');

const METHODS = [
  'capabilities', 'accountStatus', 'beginAccountSignIn', 'accountToken', 'enrollmentRequest',
  'openCheckout', 'openEnrollmentDestination', 'activatePracticeOrganization',
  'activateRegisteredPractice', 'returnToBeta', 'signOut',
];

function basePayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || payload.schemaVersion !== 1 ||
      typeof payload.requestId !== 'string' || !UUID.test(payload.requestId)) {
    throw unavailable();
  }
  return payload;
}

export function installPracticeIpc(ipcMain, renderer, practice) {
  let disposed = false;
  const recent = [], pending = new Set();

  function assertRenderer(event) {
    if (disposed || renderer.isDestroyed() || event.sender !== renderer ||
        event.senderFrame !== renderer.mainFrame || !event.senderFrame ||
        !isPackagedWorkspaceDocument(event.senderFrame.url)) throw unavailable();
  }

  function track(requestId) {
    if (recent.includes(requestId) || pending.has(requestId) || pending.size >= 32) throw unavailable();
    pending.add(requestId);
    recent.push(requestId);
    if (recent.length > 128) recent.shift();
  }

  function handle(method, run) {
    ipcMain.handle(PRACTICE_CHANNELS[method], async (event, payload) => {
      let id;
      try {
        assertRenderer(event);
        const parsed = basePayload(payload);
        track(parsed.requestId);
        id = parsed.requestId;
        const result = await run(parsed);
        assertRenderer(event);
        return result;
      } catch { throw unavailable(); }
      finally { if (id) pending.delete(id); }
    });
  }

  function exactKeys(payload, keys) {
    if (Object.keys(payload).sort().join(',') !== [...keys].sort().join(',')) throw unavailable();
  }

  handle('capabilities', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion']);
    return practice.capabilities();
  });
  handle('accountStatus', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion']);
    return practice.accountStatus();
  });
  handle('beginAccountSignIn', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion']);
    return practice.beginAccountSignIn();
  });
  handle('accountToken', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion', 'expectedRevision']);
    if (typeof payload.expectedRevision !== 'string') throw unavailable();
    return practice.accountToken({expectedRevision: payload.expectedRevision});
  });
  handle('enrollmentRequest', payload => {
    if (typeof payload.expectedRevision !== 'string' || typeof payload.operation !== 'string') throw unavailable();
    const allowed = new Set(['requestId', 'schemaVersion', 'expectedRevision', 'operation', 'body', 'idempotencyKey']);
    if (![...Object.keys(payload)].every(key => allowed.has(key))) throw unavailable();
    return practice.enrollmentRequest({
      expectedRevision: payload.expectedRevision,
      operation: payload.operation,
      ...(Object.hasOwn(payload, 'body') ? {body: payload.body} : {}),
      ...(Object.hasOwn(payload, 'idempotencyKey') ? {idempotencyKey: payload.idempotencyKey} : {}),
    });
  });
  handle('openCheckout', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion', 'expectedRevision', 'checkoutSessionId']);
    if (typeof payload.expectedRevision !== 'string' || typeof payload.checkoutSessionId !== 'string') {
      throw unavailable();
    }
    return practice.openCheckout({
      expectedRevision: payload.expectedRevision, checkoutSessionId: payload.checkoutSessionId,
    });
  });
  handle('openEnrollmentDestination', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion', 'expectedRevision', 'destination']);
    if (typeof payload.expectedRevision !== 'string' || typeof payload.destination !== 'string') {
      throw unavailable();
    }
    return practice.openEnrollmentDestination({
      expectedRevision: payload.expectedRevision, destination: payload.destination,
    });
  });
  handle('activatePracticeOrganization', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion', 'expectedRevision']);
    if (typeof payload.expectedRevision !== 'string') throw unavailable();
    return practice.activatePracticeOrganization({expectedRevision: payload.expectedRevision});
  });
  handle('activateRegisteredPractice', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion', 'expectedRevision']);
    if (typeof payload.expectedRevision !== 'string') throw unavailable();
    return practice.activateRegisteredPractice({expectedRevision: payload.expectedRevision});
  });
  handle('returnToBeta', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion', 'expectedRevision']);
    if (typeof payload.expectedRevision !== 'string') throw unavailable();
    return practice.returnToBeta({expectedRevision: payload.expectedRevision});
  });
  handle('signOut', payload => {
    exactKeys(payload, ['requestId', 'schemaVersion', 'expectedRevision']);
    if (typeof payload.expectedRevision !== 'string') throw unavailable();
    return practice.signOut({expectedRevision: payload.expectedRevision});
  });

  const remove = practice.subscribe(state => {
    if (disposed || renderer.isDestroyed() || !isPackagedWorkspaceDocument(renderer.mainFrame.url)) return;
    try { renderer.send(PRACTICE_CHANNELS.changed, state); } catch { /* Closed frame. */ }
  });

  return () => {
    if (disposed) return;
    disposed = true;
    remove();
    for (const method of METHODS) ipcMain.removeHandler(PRACTICE_CHANNELS[method]);
  };
}
