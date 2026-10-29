export const PACKAGED_WORKSPACE_DOCUMENT = 'app://cosmas/index.html';

/** A fragment changes workspace navigation, never the privileged document.
 * Compare the original document bytes exactly: URL normalization must not admit
 * credentials, ports, queries, alternate paths, encodings or other origins.
 */
export function isPackagedWorkspaceDocument(value) {
  if (typeof value !== 'string') return false;
  const fragment = value.indexOf('#');
  const document = fragment === -1 ? value : value.slice(0, fragment);
  return document === PACKAGED_WORKSPACE_DOCUMENT;
}
