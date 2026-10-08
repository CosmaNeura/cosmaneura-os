const {contextBridge, ipcRenderer} = require('electron');
const captureEnabled = false; // @desktop-native-capture-enabled@
const captureRequest = 'scribe:provider:recorder:v1', captureState = 'scribe:provider:recorder-state:v1';
const captureUuid = value => typeof value === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
const captureFields = (value, fields) => value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).sort().join(',') === fields.sort().join(',');
const captureListeners = new Set();
const privateCaptureListeners = new Set();
contextBridge.exposeInMainWorld('cosmasDesktopCapture', Object.freeze({
  enabled: captureEnabled,
  open(value) {
    if (!captureEnabled || !captureFields(value,['requestId','workspaceId','sessionId','revision']) ||
        !Object.values(value).every(captureUuid)) return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke('cosmas:workspace-capture:open:v1', value);
  },
  request(value) {
    if (!captureEnabled || !captureFields(value,['requestId','recorderId','kind']) || !captureUuid(value.requestId) ||
        value.recorderId !== null && !captureUuid(value.recorderId) ||
        !['read','start','stop','pause','continue','permissions','resume','release','deactivate'].includes(value.kind))
      return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke(captureRequest, value);
  },
  privateAcquire(value) {
    if(!captureEnabled||!captureFields(value,['requestId','revision','recordingId','consent'])||![value.requestId,value.revision,value.recordingId].every(captureUuid)||!captureFields(value.consent,['modality','participant_regions','method','all_parties_consented','granted_at','language']))return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke('cosmas:private-capture:acquire:v1',value);
  },
  privateRelease(value) {
    if(!captureEnabled||!captureFields(value,['requestId','permitId'])||!Object.values(value).every(captureUuid))return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke('cosmas:private-capture:release:v1',value);
  },
  clinicalAcquire(value) {
    if(!captureEnabled||!captureFields(value,['requestId','revision','workspaceId','sessionId','leaseId','leaseReceiptId','leaseGeneration','captureAuthorizedUntil','firstSequenceNumber'])||![value.requestId,value.revision,value.workspaceId,value.sessionId,value.leaseId,value.leaseReceiptId].every(captureUuid))return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke('cosmas:clinical-microphone:acquire:v1',value);
  },
  clinicalRelease(value) {
    if(!captureEnabled||!captureFields(value,['requestId','permitId'])||!Object.values(value).every(captureUuid))return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke('cosmas:clinical-microphone:release:v1',value);
  },
  clinicalActive(value) {
    if(!captureEnabled||!captureFields(value,['requestId','permitId'])||!Object.values(value).every(captureUuid))return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke('cosmas:clinical-microphone:active:v1',value);
  },
  privateIdle(value) {
    if(!captureEnabled||!captureFields(value,['requestId','revision'])||!Object.values(value).every(captureUuid))return Promise.reject(new Error('Desktop recording unavailable'));
    return ipcRenderer.invoke('cosmas:private-capture:idle:v1',value);
  },
  onPrivateRevoked(callback) {
    if(!captureEnabled||typeof callback!=='function'||privateCaptureListeners.size>=32)throw new Error('Desktop recording unavailable');
    const listener=(_event,value)=>{if(captureFields(value,['permitId'])&&captureUuid(value.permitId))callback(value);};privateCaptureListeners.add(listener);ipcRenderer.on('cosmas:private-capture:revoked:v1',listener);
    return()=>{privateCaptureListeners.delete(listener);ipcRenderer.removeListener('cosmas:private-capture:revoked:v1',listener);};
  },
  subscribe(callback) {
    if (!captureEnabled || typeof callback !== 'function' || captureListeners.size >= 32) throw new Error('Desktop recording unavailable');
    const listener = (_event, value) => callback(value);
    captureListeners.add(listener);ipcRenderer.on(captureState,listener);
    return () => {captureListeners.delete(listener);ipcRenderer.removeListener(captureState,listener);};
  },
}));
// @cosmaneura-navigation-dom@
// Keep lifecycle independent of authentication so startup failures also fail closed.
contextBridge.exposeInMainWorld('cosmasWorkspaceLifecycle', Object.freeze({
  notify(kind) {
    if (kind === 'ready' || kind === 'failed') ipcRenderer.send('cosmas:workspace-lifecycle:v1', kind);
  },
}));
const channels = Object.freeze({getState: 'cosmas:workspace-auth:state:v1',
  signIn: 'cosmas:workspace-auth:sign-in:v1', signOut: 'cosmas:workspace-auth:sign-out:v1',
  changed: 'cosmas:workspace-auth:changed:v1'});
const invoke = method => ipcRenderer.invoke(channels[method], {schemaVersion: 1, requestId: globalThis.crypto.randomUUID()});
const listeners = new Set();
contextBridge.exposeInMainWorld('cosmasDesktopAuth', Object.freeze({
  version: 1,
  getState: () => invoke('getState'), signIn: () => invoke('signIn'), signOut: () => invoke('signOut'),
  onStateChanged(callback) {
    if (typeof callback !== 'function' || listeners.size >= 32) throw new Error('Secure session unavailable');
    const listener = (_event, state) => callback(state);
    listeners.add(listener); ipcRenderer.on(channels.changed, listener);
    return () => { listeners.delete(listener); ipcRenderer.removeListener(channels.changed, listener); };
  },
}));
