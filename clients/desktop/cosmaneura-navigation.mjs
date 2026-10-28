import {googleNavigationConfig,validGoogleNavigationUrl} from './google-navigation.mjs';
import {microsoftNavigationConfig,validMicrosoftNavigationUrl} from './microsoft-navigation.mjs';
import {schedulingNavigationConfig, validSchedulingNavigationUrl} from './scheduling-navigation.mjs';
import {parseAuthState, sameAuthState} from './auth-helper-client.mjs';
import {isPackagedWorkspaceDocument} from './workspace-document.mjs';

export const COSMANEURA_CHANNELS = Object.freeze({
  googleCapability: 'cosmas:google:capability:v1', capability: 'cosmas:cosmaneura:capability:v1', schedulingCapability: 'cosmas:scheduling:capability:v1', microsoftCapability:'cosmas:microsoft:capability:v1', open: 'cosmas:cosmaneura:open:v1',
});
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const NOTE_PATH = /^\/notes\/appointment_[0-7][0-9a-hjkmnp-tv-z]{25}$/;
const WEB_ORIGIN = /^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const unavailable = () => new Error('Cosmaneura navigation unavailable');
const DEADLINE_MS = 12_000;

export function cosmaneuraOrigin(value = '') {
  if (value === '') return null;
  if (typeof value !== 'string' || value.length > 255 || !WEB_ORIGIN.test(value)) throw unavailable();
  const url = new URL(value);
  if (url.origin !== value || url.protocol !== 'https:' || !url.hostname || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) throw unavailable();
  return value;
}

export function parseCosmaneuraRequest(value, origin, scheduling = null, microsoft = null, google = null) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join(',') !== 'expectedRevision,href,requestId,schemaVersion' || value.schemaVersion !== 1 ||
      typeof value.requestId !== 'string' || !UUID.test(value.requestId) ||
      typeof value.expectedRevision !== 'string' || !UUID.test(value.expectedRevision) ||
      typeof value.href !== 'string' ||
      !(origin && value.href.length <= 512 && value.href.startsWith(origin) && NOTE_PATH.test(value.href.slice(origin.length))) &&
      !validSchedulingNavigationUrl(value.href, scheduling) && !validMicrosoftNavigationUrl(value.href, microsoft) && !validGoogleNavigationUrl(value.href, google)) throw unavailable();
  return Object.freeze({...value});
}

/** A reference-only browser dispatch. No token, HTTP request, or renderer navigation. */
export function installCosmaneuraNavigation({ipcMain, renderer, auth, webOrigin = '', schedulingClientId = '', schedulingCallbackUri = '', microsoftTenantId = '', microsoftClientId = '', microsoftCallbackUri = '', googleClientId = '', googleCallbackUri = '', openExternal}) {
  const origin = cosmaneuraOrigin(webOrigin);
  const scheduling = schedulingNavigationConfig(schedulingClientId, schedulingCallbackUri);
  const microsoft = microsoftNavigationConfig(microsoftTenantId,microsoftClientId,microsoftCallbackUri);
  const google = googleNavigationConfig(googleClientId,googleCallbackUri);
  let disposed = false, pending = false;
  let documentRevision = 0;
  const onNavigation = (_event, _url, _inPlace, isMainFrame) => { if (isMainFrame) documentRevision++; };
  renderer.on('did-start-navigation', onNavigation);
  const consumed = [];
  function assertRenderer(event) {
    if (disposed || renderer.isDestroyed() || event.sender !== renderer || !event.senderFrame ||
        event.senderFrame !== renderer.mainFrame || !isPackagedWorkspaceDocument(event.senderFrame.url) || !isPackagedWorkspaceDocument(renderer.getURL())) throw unavailable();
  }
  function capability(event) {
    try { assertRenderer(event); event.returnValue = origin !== null; }
    catch { event.returnValue = false; }
  }
  ipcMain.on(COSMANEURA_CHANNELS.capability, capability);
  const schedulingCapability = event => {try {assertRenderer(event); event.returnValue = scheduling !== null;} catch {event.returnValue = false;}};
  ipcMain.on(COSMANEURA_CHANNELS.schedulingCapability, schedulingCapability);
  const microsoftCapability=event=>{try{assertRenderer(event);event.returnValue=microsoft!==null;}catch{event.returnValue=false;}};
  ipcMain.on(COSMANEURA_CHANNELS.microsoftCapability,microsoftCapability);
  const googleCapability=event=>{try{assertRenderer(event);event.returnValue=google!==null;}catch{event.returnValue=false;}};
  ipcMain.on(COSMANEURA_CHANNELS.googleCapability,googleCapability);
  ipcMain.handle(COSMANEURA_CHANNELS.open, async (event, value) => {
    let timer;
    try {
      assertRenderer(event);
      const request = parseCosmaneuraRequest(value, origin, scheduling, microsoft, google);
      if (pending || consumed.includes(request.requestId)) throw unavailable();
      const before = parseAuthState(auth.snapshot());
      if (before.phase !== 'ready' || before.revision !== request.expectedRevision) throw unavailable();
      consumed.push(request.requestId); if (consumed.length > 128) consumed.shift();
      pending = true;
      const expectedDocument = documentRevision;
      let expired = false;
      const operation = (async () => {
        try {
          const current = parseAuthState(await auth.getState());
          assertRenderer(event);
          if (expired || documentRevision !== expectedDocument || !sameAuthState(before, current) ||
              !sameAuthState(current, parseAuthState(auth.snapshot()))) throw unavailable();
          // This is the only effect. The OS/browser may later redirect or require login.
          await openExternal(request.href);
          if (expired) throw unavailable();
          return {schemaVersion: 1, requestId: request.requestId, status: 'opened'};
        } finally {
          // An uncertain OS operation keeps this gate until it actually settles.
          pending = false;
        }
      })();
      const deadline = new Promise((_resolve, reject) => {
        timer = setTimeout(() => { expired = true; reject(unavailable()); }, DEADLINE_MS);
      });
      return await Promise.race([operation, deadline]);
    } catch { throw unavailable(); }
    finally { clearTimeout(timer); }
  });
  return () => {
    disposed = true;
    ipcMain.removeListener(COSMANEURA_CHANNELS.capability, capability);
    ipcMain.removeListener(COSMANEURA_CHANNELS.schedulingCapability, schedulingCapability);
    ipcMain.removeListener(COSMANEURA_CHANNELS.microsoftCapability,microsoftCapability);
    ipcMain.removeListener(COSMANEURA_CHANNELS.googleCapability,googleCapability);
    ipcMain.removeHandler(COSMANEURA_CHANNELS.open);
    renderer.removeListener('did-start-navigation', onNavigation);
  };
}
