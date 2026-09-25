import {parseAuthState} from './auth-helper-client.mjs';

export const AUTH_CHANNELS = Object.freeze({getState: 'cosmas:workspace-auth:state:v1',
  signIn: 'cosmas:workspace-auth:sign-in:v1', signOut: 'cosmas:workspace-auth:sign-out:v1',
  changed: 'cosmas:workspace-auth:changed:v1'});
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const unavailable = () => new Error('Secure session operation unavailable');

export function installAuthIpc(ipcMain, renderer, auth) {
  let disposed = false;
  const recent = [], pending = new Set();
  // Reuses Scribe a0d7f24's sender/main-frame checks, with an exact document URL.
  function assertRenderer(event) {
    if (disposed || renderer.isDestroyed() || event.sender !== renderer ||
        event.senderFrame !== renderer.mainFrame || !event.senderFrame ||
        event.senderFrame.url !== 'app://cosmas/index.html') throw unavailable();
  }
  for (const method of ['getState', 'signIn', 'signOut']) {
    ipcMain.handle(AUTH_CHANNELS[method], async (event, payload) => {
      let id;
      try {
        assertRenderer(event);
        if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
            Object.keys(payload).sort().join(',') !== 'requestId,schemaVersion' || payload.schemaVersion !== 1 ||
            typeof payload.requestId !== 'string' || !UUID.test(payload.requestId) ||
            recent.includes(payload.requestId) || pending.has(payload.requestId) || pending.size >= 32) throw unavailable();
        id = payload.requestId; pending.add(id); recent.push(id); if (recent.length > 128) recent.shift();
        const result = parseAuthState(await auth[method]());
        assertRenderer(event); return result;
      } catch { throw unavailable(); }
      finally { if (id) pending.delete(id); }
    });
  }
  const remove = auth.subscribe(state => {
    if (disposed || renderer.isDestroyed() || renderer.mainFrame.url !== 'app://cosmas/index.html') return;
    try { renderer.send(AUTH_CHANNELS.changed, parseAuthState(state)); } catch { /* Closed frame or invalid state. */ }
  });
  return () => {
    if (disposed) return;
    disposed = true; remove();
    for (const method of ['getState', 'signIn', 'signOut']) ipcMain.removeHandler(AUTH_CHANNELS[method]);
  };
}
