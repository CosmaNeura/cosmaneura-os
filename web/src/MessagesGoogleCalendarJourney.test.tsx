import {act} from 'react';
import {waitMessagesJourney as wait, MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {openDraftStore} from './draft-store';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
import {conversationsApi} from './conversations-api';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import type {CalendarRehearsalStats} from '../ux-acceptance/google-calendar';
import {googleCalendarApi,type GoogleCalendarReceipt} from './google-calendar-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');

// Journey waits may legitimately exceed Vitest's 5s default under CI load.
vi.setConfig({testTimeout: MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement,idb:IDBFactory;
const storage=({scope}:{scope:string})=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const task=()=>[...host.querySelectorAll<HTMLElement>('.ehr-read-task[aria-label="Review Google Calendar"]')].find(visible);

async function click(name:string){let sent=false;await wait(()=>{if(sent)return;const target=button(name);expect(target,name).toBeTruthy();expect(target!.disabled,name).toBe(false);expect(target!.isConnected,name).toBe(true);sent=true;target!.focus({preventScroll:true});target!.click();});}
async function type(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openChat(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()).toBeTruthy());await wait(()=>expect(row()!.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()).toBeTruthy());await wait(()=>expect(question()!.disabled).toBe(false));}
const stats=()=>(window as Window&{calendarRehearsalStats?:CalendarRehearsalStats}).calendarRehearsalStats!;
async function openTask(){await click('Details');await click('Choose notes or sources');await click('Review Google Calendar');await wait(()=>expect(task()).toBeDefined());await wait(()=>expect(['Check calendar access','Restore saved calendar work','Check saved calendar result'].some(name=>button(name)?.disabled===false)).toBe(true));}
async function loadEvent(){await openTask();await click('Check calendar access');await click('Load next 7 days');await wait(()=>expect(task()?.querySelector<HTMLButtonElement>('[data-calendar-event]')).toBeTruthy());await wait(()=>expect(task()!.querySelector<HTMLButtonElement>('[data-calendar-event]')!.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('[data-calendar-event]')!.click());await wait(()=>expect(button('Use current visit')).toBeTruthy());await wait(()=>expect(button('Use current visit')!.disabled).toBe(false));}
async function saveEvent(){await loadEvent();await click('Use current visit');await wait(()=>expect(task()?.querySelector<HTMLInputElement>('input[type="checkbox"]')).toBeTruthy());await wait(()=>expect(task()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(false));for(const input of task()!.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))await act(async()=>input.click());await click('Save calendar summary to visit');await wait(()=>expect(button('Ask Chief about this calendar summary')).toBeTruthy());await wait(()=>expect(button('Ask Chief about this calendar summary')!.disabled).toBe(false));}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','?scenario=google-calendar-happy#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it('opens one complete Calendar task from Chief and returns the exact draft, focus and reading position without reading events',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChat();await type('Keep exact Chief calendar directions.');
 const scroll=()=>host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll(),'scrollHeight',{configurable:true,value:1000});Object.defineProperty(scroll(),'clientHeight',{configurable:true,value:200});scroll().scrollTop=230;await act(async()=>scroll().dispatchEvent(new Event('scroll')));const marks=vi.spyOn(conversationsApi,'mark');
 await openTask();expect(host.querySelectorAll('.google-calendar-panel')).toHaveLength(1);expect(host.querySelector('.messages-details')).toBeNull();expect(stats()).toMatchObject({status:0,observes:0,reviews:0});const owner=host.querySelector('.google-calendar-panel');
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(button('Details')));expect(question().value).toBe('Keep exact Chief calendar directions.');expect(scroll().scrollTop).toBe(230);expect(marks).not.toHaveBeenCalled();
 await openTask();expect(host.querySelector('.google-calendar-panel')).toBe(owner);expect(stats().observes).toBe(0);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('reviews one event with three acknowledgments, saves an exact source and prepares Chief without sending',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChat();await type('Retain my current instructions.');await saveEvent();const exact=task()!.querySelector('pre')!.textContent;
 await click('Ask Chief about this calendar summary');await wait(()=>expect(question().disabled).toBe(false));expect(question().value).toContain('Retain my current instructions.');expect(question().value).toContain('Review the human-selected calendar summary');expect(question().value).not.toContain(exact);expect(task()).toBeUndefined();expect(stats()).toMatchObject({status:1,observes:1,reviews:1,externalCalls:0});expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 const card=host.querySelector<HTMLElement>('[aria-label="Saved Google Calendar summary"]');expect(card).not.toBeNull();await act(async()=>card!.querySelector<HTMLButtonElement>('button')!.click());await wait(()=>expect(document.activeElement?.id.startsWith('source-')).toBe(true));expect(document.activeElement?.textContent).toContain(exact);await click('‹ Back to Chief of Staff');expect(question().value).toContain('Retain my current instructions.');expect(stats().observes).toBe(1);
});
it('returns with an unconfirmed persisted read and restores its exact key after a true remount without another observation',async()=>{
 history.replaceState(null,'','?scenario=google-calendar-unconfirmed#cosmas/home');await openChat();await type('Retain this draft through Calendar recovery.');await openTask();await click('Check calendar access');await click('Load next 7 days');await click('Check saved calendar result');const request=stats().requests.find(r=>r.action==='observe')!;
 expect(task()?.textContent).toContain('unconfirmed');await click('‹ Back to Chief of Staff');expect(question().value).toBe('Retain this draft through Calendar recovery.');await openTask();await click('Check saved calendar result');expect(stats().observes).toBe(1);await click('‹ Back to Chief of Staff');await click('‹ Messages');
 await act(async()=>root.unmount());root=createRoot(host);await installFixtures();await mount();await openChat();expect(question().value).toBe('Retain this draft through Calendar recovery.');await openTask();await click('Restore saved calendar work');await click('Check saved calendar result');expect(stats()).toMatchObject({observes:0,reviews:0,resolves:1});expect(stats().requests.find(r=>r.action==='resolve')?.key).toBe(request.key);expect(button('Load next 7 days')?.disabled).toBe(true);await click('‹ Back to Chief of Staff');
});
it('retains the initial journal load across Back and reveal without a second mount or new event read',async()=>{
 await openChat();const load=DraftJournal.prototype.load;let release!:(value:Awaited<ReturnType<typeof load>>)=>void,count=0;
 vi.spyOn(DraftJournal.prototype,'load').mockImplementation(function(this:DraftJournal,address){if(address===accountEditorAddress('google-calendar')){count++;if(count===1)return new Promise(resolve=>{release=resolve;});}return load.call(this,address);});
 await click('Details');await click('Choose notes or sources');await click('Review Google Calendar');await wait(()=>expect(release).toBeTypeOf('function'));await click('‹ Back to Chief of Staff');await click('Details');await click('Choose notes or sources');await click('Review Google Calendar');await act(async()=>release(null));await wait(()=>expect(button('Check calendar access')).toBeTruthy());await wait(()=>expect(button('Check calendar access')!.disabled).toBe(false));expect(count).toBe(1);expect(host.querySelectorAll('.google-calendar-panel')).toHaveLength(1);expect(stats().observes).toBe(0);
});
it('keeps missing permission behind explicit access and preserves the Chief return',async()=>{
 await act(async()=>root.unmount());root=createRoot(host);history.replaceState(null,'','?scenario=google-calendar-consent#cosmas/home');await installFixtures(true);await mount();await openChat();await type('No implicit consent.');await openTask();await click('Check calendar access');expect(button('Load next 7 days')?.disabled).toBe(true);expect(button('Add calendar access')?.disabled).toBe(false);expect(stats().observes).toBe(0);await click('‹ Back to Chief of Staff');expect(question().value).toBe('No implicit consent.');
});
it('refuses stale saved event preparation after the account grant changes without another read',async()=>{
 await openChat();await type('Keep these directions.');await saveEvent();await act(async()=>{(window as Window&{calendarRehearsalControls?:{changeGrant:()=>void}}).calendarRehearsalControls!.changeGrant();});await click('Check calendar access');expect(task()?.querySelector('pre')).toBeNull();expect(button('Ask Chief about this calendar summary')).toBeUndefined();expect(stats()).toMatchObject({observes:1,reviews:1});await click('‹ Back to Chief of Staff');expect(question().value).toBe('Keep these directions.');
});
it('cancels a delayed Details admission after dismissal and refuses an old return after native suspension',async()=>{
 const native={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000901',isCurrent:()=>true}};await act(async()=>root.render(<EncounterWorkspace authenticated={native} draftStorage={storage}/>));await openChat();await type('Retain native calendar directions.');await click('Details');await click('Choose notes or sources');const prior=await workspaceApi.team(native);let finish!:(value:typeof prior)=>void;vi.spyOn(workspaceApi,'team').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await act(async()=>button('Review Google Calendar')!.click());await wait(()=>expect(finish).toBeTypeOf('function'));await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));await act(async()=>finish(prior));expect(task()).toBeUndefined();await openTask();let oldReturn:FrameRequestCallback|undefined;vi.spyOn(window,'requestAnimationFrame').mockImplementationOnce(callback=>{oldReturn=callback;return 100005;});await click('‹ Back to Chief of Staff');await act(async()=>notifyNativeWorkspaceForeground(native,false));await act(async()=>notifyNativeWorkspaceForeground(native,true));button('Details')!.focus({preventScroll:true});const scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;scroll.scrollTop=83;await act(async()=>oldReturn!(0));expect(document.activeElement).toBe(button('Details'));await wait(()=>expect(scroll.scrollTop).toBe(83));expect(question().value).toBe('Retain native calendar directions.');expect(stats().observes).toBe(0);
});
it('blocks Back during an active request continuation and fences a late event read after native background',async()=>{
 const native={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000902',isCurrent:()=>true}};await act(async()=>root.render(<EncounterWorkspace authenticated={native} draftStorage={storage}/>));await openChat();await type('Hold this draft.');await openTask();await click('Check calendar access');const observe=googleCalendarApi.observe;let release!:(value:GoogleCalendarReceipt)=>void,receipt!:GoogleCalendarReceipt;
 vi.spyOn(googleCalendarApi,'observe').mockImplementationOnce(async(...args)=>{receipt=await observe(...args);return new Promise(resolve=>{release=resolve;});});await click('Load next 7 days');await wait(()=>expect(release).toBeTypeOf('function'));expect(button('‹ Back to Chief of Staff')?.disabled).toBe(true);await act(async()=>notifyNativeWorkspaceForeground(native,false));await act(async()=>notifyNativeWorkspaceForeground(native,true));await act(async()=>release(receipt));await wait(()=>expect(button('Restore saved calendar work')).toBeTruthy());await wait(()=>expect(button('Restore saved calendar work')!.disabled).toBe(false));expect(task()?.querySelector('pre')).toBeNull();await click('Restore saved calendar work');await click('Check saved calendar result');expect(stats()).toMatchObject({observes:1,resolves:1});await click('‹ Back to Chief of Staff');expect(question().value).toBe('Hold this draft.');
});

it('adds Calendar to private Chief without a visit, preserves Back and unsent drafts, and reopens the saved source',async()=>{
 await act(async()=>root.unmount());root=createRoot(host);history.replaceState(null,'','?scenario=google-calendar-private#cosmas/home');await installFixtures(true);await mount();
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),visitOpen=vi.spyOn(workspaceApi,'open');await openChat();
 const notes=host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value,directions='Private planning directions stay with the original context.';
 await type(directions);await openTask();await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(button('Details')));expect(question().value).toBe(directions);expect(stats().observes).toBe(0);
 await openTask();await click('Check calendar access');await click('Load next 7 days');await wait(()=>expect(task()?.querySelector<HTMLButtonElement>('[data-calendar-event]')).toBeTruthy());await wait(()=>expect(task()!.querySelector<HTMLButtonElement>('[data-calendar-event]')!.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('[data-calendar-event]')!.click());
 expect(button('Choose a visit')).toBeUndefined();await click('Use this notebook');expect(task()?.textContent).toContain('No patient or visit is linked.');await wait(()=>{expect(task()?.querySelectorAll('input[type="checkbox"]')).toHaveLength(3);expect(task()?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.disabled).toBe(false);});
 for(const input of task()!.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))await act(async()=>input.click());await click('Add to notebook');await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));
 const request=stats().requests.find(row=>row.action==='review')!.body;expect(request).toMatchObject({reviewed_private_notebook:true});expect(request).not.toHaveProperty('reviewed_visit');
 expect(ask).not.toHaveBeenCalled();await click('Prepare Chief draft');await wait(()=>expect(question().disabled).toBe(false));
 const draft=question().value;expect(draft).toContain(directions);expect(draft).toContain('nonclinical planning in this private notebook');expect(draft).not.toContain('clinical note and email sources');expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(notes);
 expect(visitOpen).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();expect(stats()).toMatchObject({observes:1,reviews:1,externalCalls:0});
 await click('‹ Messages');await act(async()=>root.unmount());root=createRoot(host);await installFixtures();await mount();await openChat();expect(question().value).toBe(draft);expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(notes);
 const card=host.querySelector<HTMLElement>('[aria-label="Saved Google Calendar summary"]')!;expect(card).not.toBeNull();await act(async()=>card.querySelector<HTMLButtonElement>('button')!.click());await wait(()=>expect(document.activeElement?.id.startsWith('source-')).toBe(true));await click('‹ Back to Chief of Staff');expect(question().value).toBe(draft);expect(stats().observes).toBe(0);
 await openTask();await click('Restore saved calendar work');expect(task()?.querySelector('pre')).toBeNull();await click('Check calendar access');await wait(()=>expect(button('Prepare Chief draft')?.disabled).toBe(false));expect(stats()).toMatchObject({observes:0,inspects:1,reviews:0});
});

it('blocks departure while the exact pending request is still being persisted and sends nothing until it is durable',async()=>{
 await openChat();await openTask();await click('Check calendar access');const persist=DraftJournal.prototype.persist;let release!:(value:void)=>void,entered=false;
 vi.spyOn(DraftJournal.prototype,'persist').mockImplementation(async function(this:DraftJournal,address,value){if(address===accountEditorAddress('google-calendar')&&!entered){entered=true;await new Promise<void>(resolve=>{release=resolve;});}return persist.call(this,address,value);});
 await click('Load next 7 days');await wait(()=>expect(release).toBeTypeOf('function'));expect(stats().observes).toBe(0);expect(button('‹ Back to Chief of Staff')?.disabled).toBe(true);await act(async()=>release());await wait(()=>expect(stats().observes).toBe(1));await click('‹ Back to Chief of Staff');
});

it('explains the pending Calendar restriction in direct Gmail work and keeps the exact Calendar recovery reachable',async()=>{
 history.replaceState(null,'','?scenario=google-calendar-unconfirmed#cosmas/home');await openChat();await type('Keep both source tasks separate.');await openTask();await click('Check calendar access');await click('Load next 7 days');await click('Check saved calendar result');const original=stats().requests.find(r=>r.action==='observe')!.key;await click('‹ Back to Chief of Staff');await click('Details');await click('Choose notes or sources');await click('Review Gmail email');
 await wait(()=>expect([...host.querySelectorAll('.ehr-read-task')].find(e=>visible(e)&&e.getAttribute('aria-label')==='Review Gmail email')?.textContent).toContain('Review your saved Calendar work before continuing with email.'));expect(button('Check email access')?.disabled).toBe(true);expect(button('‹ Back to Chief of Staff')?.disabled).toBe(false);await click('‹ Back to Chief of Staff');await openTask();await click('Check saved calendar result');expect(stats().requests.filter(r=>r.action==='resolve').every(r=>r.key===original)).toBe(true);expect(stats().observes).toBe(1);await click('‹ Back to Chief of Staff');expect(question().value).toBe('Keep both source tasks separate.');
});
