import {randomUUID} from 'node:crypto';
import {closedAuthState, parseAuthState, sameAuthState} from './auth-helper-client.mjs';

const unavailable = () => new Error('Native session unavailable');

/** Main-process state only; returned getToken must never be exposed by preload. */
export async function createDesktopAuthSession({enabled = false, createHelper, accessStore}) {
  let state = closedAuthState(enabled ? 'loading' : 'disabled');
  let native = null, helper = null, removeListener = null;
  let access = 'needs_login', storageFailed = false, disposed = false, pending = null;
  let version = 0, bindingRevision = null;
  const listeners = new Set();
  function change(phase, identity = null, nativeRevision = null) {
    const same = state.phase === phase && bindingRevision === nativeRevision &&
      state.identity?.userId === identity?.userId && state.identity?.sessionId === identity?.sessionId &&
      state.identity?.organizationId === identity?.organizationId;
    if (same) return;
    bindingRevision = nativeRevision;
    state = Object.freeze({phase, revision: randomUUID(), identity}); version++;
    for (const listener of listeners) { try { listener(state); } catch { /* No raw callback errors. */ } }
  }
  function reconcile() {
    if (disposed || storageFailed) return change('unavailable');
    if (!enabled) return change('disabled');
    if (pending) return change(pending.action === 'signIn' ? 'signingIn' : 'signOutPending');
    if (!native) return change('unavailable');
    if (['disabled', 'loading', 'unavailable'].includes(native.phase)) return change(native.phase);
    if (access === 'logout_pending') return change('signOutPending');
    if (access !== 'allowed') return change('signedOut');
    change(native.phase, native.identity, native.phase === 'ready' ? native.revision : null);
  }
  async function persist(next) {
    try { await accessStore.write(next); access = next; }
    catch { storageFailed = true; change('unavailable'); throw unavailable(); }
  }
  const currentOperation = operation => !disposed && !storageFailed && pending === operation;
  async function getState() {
    if (!helper || disposed || storageFailed) return state;
    const observed = version;
    try {
      const next = await helper.getState();
      if (version === observed && !disposed && !storageFailed) { native = parseAuthState(next); reconcile(); }
    } catch { if (version === observed) change('unavailable'); }
    return state;
  }
  async function signIn() {
    if (!helper || disposed || storageFailed || pending) throw unavailable();
    const priorAccess = access;
    const operation = {id: randomUUID(), action: 'signIn'};
    pending = operation; reconcile();
    try {
      await persist('logout_pending');
      if (!currentOperation(operation)) throw unavailable();
      if (priorAccess === 'logout_pending') await helper.signOut();
      if (!currentOperation(operation)) throw unavailable();
      const result = parseAuthState(await helper.signIn());
      if (!currentOperation(operation) || result.phase !== 'ready') throw unavailable();
      await persist('allowed');
      if (!currentOperation(operation)) throw unavailable();
      pending = null; native = result; reconcile(); return state;
    } catch {
      if (pending === operation) { pending = null; reconcile(); }
      throw unavailable();
    }
  }
  async function signOut() {
    if (!helper || disposed || storageFailed || (pending && pending.action !== 'signIn')) throw unavailable();
    const operation = {id: randomUUID(), action: 'signOut'};
    pending = operation; reconcile();
    try {
      await persist('logout_pending');
      if (!currentOperation(operation)) throw unavailable();
      const result = parseAuthState(await helper.signOut());
      if (!currentOperation(operation) || result.phase !== 'signedOut') throw unavailable();
      await persist('needs_login');
      if (!currentOperation(operation)) throw unavailable();
      pending = null; native = result; reconcile(); return state;
    } catch {
      if (pending === operation) { pending = null; reconcile(); }
      throw unavailable();
    }
  }
  async function getToken(revision) {
    const expected = await getState();
    if (disposed || storageFailed || pending || expected.phase !== 'ready' || expected.revision !== revision ||
        !native || access !== 'allowed') throw unavailable();
    const nativeRevision = native.revision;
    try {
      const token = await helper.getToken(nativeRevision);
      await getState();
      if (disposed || storageFailed || pending || access !== 'allowed' || !sameAuthState(state, expected) ||
          native?.revision !== nativeRevision || typeof token !== 'string' || token.length > 8192 ||
          !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(token)) throw unavailable();
      return token;
    } catch { throw unavailable(); }
  }
  /** Trusted recorder only. The renderer auth surface never forwards this API. */
  async function sourceRequest(method, payload, revision) {
    if (!['sourcePrepare','sourceAuthorize','sourceExtend','sourceRelease','sourceStopped','sourcePreparationRelease'].includes(method) ||
        !payload || typeof payload !== 'object' || Array.isArray(payload) || Object.hasOwn(payload,'revision')) throw unavailable();
    const start = ['sourcePrepare','sourceAuthorize','sourceExtend'].includes(method);
    const expected = await getState();
    if (!helper || disposed || storageFailed || pending || access !== 'allowed' ||
        expected.phase !== 'ready' || !native || start && expected.revision !== revision) throw unavailable();
    const nativeRevision = native.revision;
    const result = await helper.sourceRequest(method, {...payload, ...(['sourcePrepare','sourceExtend'].includes(method) ? {revision:nativeRevision} : {})});
    // A stop reply remains useful after same-account reauthentication; its
    // native owner checks original identity and never creates a fresh start.
    if (start && (disposed || pending || !sameAuthState(state,expected) || native?.revision !== nativeRevision)) throw unavailable();
    return result;
  }
  if (enabled) {
    try {
      access = await accessStore.read();
      if (!['needs_login', 'logout_pending', 'allowed'].includes(access)) throw unavailable();
      helper = createHelper();
      removeListener = helper.subscribe(value => {
        if (disposed) return;
        try { native = parseAuthState(value); reconcile(); }
        catch { storageFailed = true; change('unavailable'); helper.close(); }
      });
      await getState();
    } catch { storageFailed = true; change('unavailable'); helper?.close(); }
  }
  return Object.freeze({
    getState, signIn, signOut, getToken, sourceRequest, snapshot: () => state,
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    close: () => { if (disposed) return; disposed = true; removeListener?.(); reconcile(); helper?.close(); },
  });
}
