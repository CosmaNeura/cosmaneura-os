const {contextBridge, ipcRenderer} = require('electron');
// One-way lifecycle notices carry no workspace values and return no native capabilities.
contextBridge.exposeInMainWorld('cosmasWorkspaceLifecycle', Object.freeze({
  notify(kind) {
    if (kind === 'ready' || kind === 'failed') ipcRenderer.send('cosmas:workspace-lifecycle:v1', kind);
  },
}));
