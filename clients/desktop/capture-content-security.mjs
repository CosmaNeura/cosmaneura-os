/** Allow only explicitly configured HTTPS upload origins; keep all other Scribe directives. */
export function captureContentSecurityPolicy(base, origins = []) {
  if (!Array.isArray(origins) || origins.length > 4) throw new Error('Invalid capture upload origins');
  for (const origin of origins) {
    if (typeof origin !== 'string' || origin.length > 253 ||
        !/^https:\/\/[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?$/.test(origin)) {
      throw new Error('Invalid capture upload origin');
    }
    const url = new URL(origin);
    if (url.origin !== origin || !url.hostname.includes('.') ||
        url.hostname.split('.').some(label => !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label))) {
      throw new Error('Invalid capture upload origin');
    }
  }
  const directives = base.split(';').map(value => value.trim());
  const indexes = directives.flatMap((value, index) => /^connect-src(?:\s|$)/.test(value) ? [index] : []);
  if (indexes.length !== 1 || directives[indexes[0]] !== "connect-src 'self'") {
    throw new Error('Unexpected retained capture policy');
  }
  if (!origins.length) return base;
  directives[indexes[0]] += ' ' + [...new Set(origins)].join(' ');
  return directives.join('; ');
}

/** The authenticated UI creates a blob only after verifying private PDF bytes. */
export function privateDocumentContentSecurityPolicy(base) {
  if (typeof base !== 'string') throw new Error('Invalid private document policy');
  const directives = base.split(';').map(value => value.trim()).filter(Boolean);
  const values = name => directives.filter(value => value.split(/\s/)[0] === name);
  for (const name of ['default-src', 'object-src']) {
    const found = values(name);
    if (found.length !== 1 || found[0] !== `${name} 'none'`) throw new Error('Unexpected retained document policy');
  }
  const frames = values('frame-src');
  if (frames.length > 1 || frames.length === 1 && frames[0] !== "frame-src 'none'") throw new Error('Unexpected retained frame policy');
  return [...directives.filter(value => !value.startsWith('frame-src ')), 'frame-src blob:'].join('; ');
}

/** The authenticated UI verifies encrypted private PCM before creating its local WAV blob. */
export function privateRecordingContentSecurityPolicy(base) {
  if (typeof base !== 'string') throw new Error('Invalid private recording policy');
  const directives = base.split(';').map(value => value.trim()).filter(Boolean);
  const values = name => directives.filter(value => value.split(/\s/)[0].toLowerCase() === name);
  for (const name of ['default-src', 'object-src', 'media-src']) {
    const found = values(name);
    if (found.length !== 1 || found[0] !== `${name} 'none'`) throw new Error('Unexpected retained recording policy');
  }
  return directives.map(value => value === "media-src 'none'" ? 'media-src blob:' : value).join('; ');
}

/** Electron supports one response-header handler. Replace only its CSP value after Scribe setup. */
export function installCaptureContentSecurityPolicy(webRequest, policy) {
  webRequest.onHeadersReceived((details, callback) => {
    const headers = Object.fromEntries(Object.entries(details.responseHeaders ?? {})
      .filter(([name]) => name.toLowerCase() !== 'content-security-policy'));
    callback({responseHeaders: {...headers, 'Content-Security-Policy': [policy]}});
  });
}
