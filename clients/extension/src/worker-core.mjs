import profile from '../local-profile.json' with {type: 'json'};
const denied = () => ({state: 'request_refused'});
export function panelSender(sender) {
  return sender?.id === profile.extensionId && sender?.url === `${profile.extensionOrigin}/panel.html` && !sender.tab;
}
export async function boxCall(getClerk, fetcher, path, body) {
  if (!['/workspace/extension-session', '/workspace/screen-observations'].includes(path)) return denied();
  try {
    const clerk = await getClerk();
    if (!clerk?.session || clerk.session.status !== 'active' || clerk.organization?.id !== clerk.proofOrganization) return {state: 'sign_in_required'};
    const token = await clerk.session.getToken({skipCache: true});
    if (!token) return {state: 'sign_in_required'};
    const response = await fetcher(profile.apiOrigin + path, {method: body ? 'POST' : 'GET',
      headers: {Authorization: `Bearer ${token}`, ...(body ? {'Content-Type': 'application/json'} : {})},
      ...(body ? {body: JSON.stringify(body)} : {}), credentials: 'omit', redirect: 'error', cache: 'no-store'});
    if (!response.ok) return {state: response.status === 401 || response.status === 403 ? 'sign_in_required' : 'box_unavailable'};
    return {state: 'connected', result: await response.json()};
  } catch { return {state: 'box_unavailable'}; }
}
export async function handleMessage(message, sender, {getClerk, fetcher, readFixture}) {
  if (!panelSender(sender)) return denied();
  try {
    switch (message?.type) {
      case 'connect': return boxCall(getClerk, fetcher, '/workspace/extension-session');
      case 'read-fixture': {
        const screen = await readFixture();
        if (screen?.state !== 'recognised') return {state: 'screen_not_recognised'};
        return boxCall(getClerk, fetcher, '/workspace/screen-observations', {rows: screen.rows});
      }
      case 'sign-in': {
        if (typeof message.identifier !== 'string' || typeof message.password !== 'string'
            || !message.identifier || !message.password || message.identifier.length > 255 || message.password.length > 1024) return denied();
        const clerk = await getClerk();
        if (!clerk) return {state: 'sign_in_unavailable'};
        const attempt = await clerk.client.signIn.create({identifier: message.identifier, password: message.password});
        if (attempt.status !== 'complete' || !attempt.createdSessionId) return {state: 'sign_in_step_required'};
        await clerk.setActive({session: attempt.createdSessionId, organization: clerk.proofOrganization});
        return boxCall(getClerk, fetcher, '/workspace/extension-session');
      }
      case 'sign-out': {
        const clerk = await getClerk();
        await clerk?.signOut();
        return {state: 'sign_in_required'};
      }
      default: return denied();
    }
  } catch { return {state: 'sign_in_unavailable'}; }
}
