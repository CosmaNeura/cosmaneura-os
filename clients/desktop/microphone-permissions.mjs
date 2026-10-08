const ENTRY = 'app://cosmas/index.html';
const ORIGIN = 'app://cosmas';
const sameOrigin = value => value === ORIGIN || value === ORIGIN + '/';

/** Independent, default-off shell gate. The recorder still requires consent and explicit Start. */
export function installMicrophonePermissions(renderer, auth, enabled = false, admitted = () => false) {
  if (typeof enabled !== 'boolean') throw new Error('Invalid microphone configuration');
  if(typeof admitted!=='function')throw new Error('Invalid microphone admission');
  function current(contents, permission, details) {
    try {
      return enabled && contents === renderer && permission === 'media' &&
        !renderer.isDestroyed() && renderer.getURL() === ENTRY && renderer.mainFrame.url === ENTRY &&
        details?.isMainFrame === true && details.requestingUrl === ENTRY &&
        (details.securityOrigin === undefined || sameOrigin(details.securityOrigin)) &&
        (details.embeddingOrigin === undefined || sameOrigin(details.embeddingOrigin)) &&
        auth.snapshot().phase === 'ready' && admitted() === true;
    } catch { return false; }
  }
  renderer.session.setPermissionCheckHandler((contents, permission, requestingOrigin, details) =>
    sameOrigin(requestingOrigin) && current(contents, permission, details) && details.mediaType === 'audio');
  renderer.session.setPermissionRequestHandler((contents, permission, callback, details) => {
    const allowed = current(contents, permission, details) && Array.isArray(details.mediaTypes) &&
      details.mediaTypes.length === 1 && details.mediaTypes[0] === 'audio';
    callback(allowed);
  });
}
