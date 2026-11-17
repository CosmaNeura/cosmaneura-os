import profile from '../local-profile.json' with {type: 'json'};
import pack from '../screen-pack.json' with {type: 'json'};
import {readScreen} from './screen.mjs';
if (location.origin === profile.fixtureOrigin && location.pathname === '/schedule.html') {
  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (sender.id === profile.extensionId && message?.type === 'read-screen') reply(readScreen(document, pack));
  });
}
