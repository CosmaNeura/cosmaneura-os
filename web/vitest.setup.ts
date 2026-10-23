import {beforeEach,vi} from 'vitest';

// Each case starts with a fresh browser route; deliberate remounts within a
// case retain their URL unless that fixture explicitly navigates Home.
beforeEach(()=>{if(typeof window!=='undefined'&&window.history&&typeof window.history.replaceState==='function'&&window.location){window.history.replaceState(null,'',window.location.pathname+window.location.search);window.scrollTo=vi.fn();}});
