import {createClerkClient} from '@clerk/chrome-extension/client';
import profile from '../local-profile.json' with {type: 'json'};
import {handleMessage} from './worker-core.mjs';
const config = __CLERK_CONFIG__;
async function getClerk() {
  if (!config.publishableKey || chrome.runtime.id !== profile.extensionId) return null;
  const clerk = await createClerkClient({publishableKey: config.publishableKey, background: true});
  clerk.proofOrganization = config.organization;
  // The backend repeats issuer, organization, active human and Box binding checks.
  return clerk;
}
async function readFixture() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id || tab.url !== `${profile.fixtureOrigin}/schedule.html`) return null;
  try { return await chrome.tabs.sendMessage(tab.id, {type: 'read-screen'}); } catch { return null; }
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  handleMessage(message, sender, {getClerk, fetcher: fetch, readFixture}).then(reply, () => reply({state: 'request_refused'}));
  return true;
});
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
