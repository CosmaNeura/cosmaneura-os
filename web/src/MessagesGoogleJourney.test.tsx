import {act} from 'react';
import {waitMessagesJourney as wait, MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
vi.setConfig({testTimeout: MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {openDraftStore} from './draft-store';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
import {conversationsApi} from './conversations-api';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import {GMAIL_REHEARSAL_TEXT,type GmailRehearsalStats} from '../ux-acceptance/gmail';
import {googleMessageApi,type GoogleMessageReviewResponse} from './google-message-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement,idb:IDBFactory;
const storage=({scope}:{scope:string})=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const task=()=>[...host.querySelectorAll<HTMLElement>('.ehr-read-task[aria-label="Review Gmail email"]')].find(visible);

async function click(name:string){await wait(()=>expect(button(name)).toBeTruthy());await wait(()=>expect(button(name)!.disabled).toBe(false));await act(async()=>{button(name)!.focus({preventScroll:true});button(name)!.click();});}
async function type(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openChat(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()).toBeTruthy());await wait(()=>expect(row()!.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()).toBeTruthy());await wait(()=>expect(question()!.disabled).toBe(false));}
const stats=()=>(window as Window&{gmailRehearsalStats?:GmailRehearsalStats}).gmailRehearsalStats!;
async function openTask(){await click('Details');await click('Choose notes or sources');await click('Review Gmail email');await wait(()=>expect(task()).toBeDefined());await wait(()=>expect(button('Check email access')??button('Restore saved email work')).toBeTruthy());await wait(()=>expect((button('Check email access')??button('Restore saved email work'))!.disabled).toBe(false));}
async function readEmail(){await openTask();await click('Check email access');await click('Select email');await wait(()=>expect(task()?.querySelector<HTMLButtonElement>('.google-message-list button')).toBeTruthy());await wait(()=>expect(task()!.querySelector<HTMLButtonElement>('.google-message-list button')!.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('.google-message-list button')!.click());await click('Read full email');}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('opens the existing Gmail review from Chief Details and returns the exact draft to the visible opener',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChat();await type('Keep my exact Chief directions.');const opener=button('Details')!;
 await click('Details');await click('Choose notes or sources');await click('Review Gmail email');await wait(()=>expect(task()).toBeDefined());
 expect(host.querySelectorAll('.google-message-panel')).toHaveLength(1);expect(host.querySelector('.messages-details')).toBeNull();
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(button('Details')));expect(opener.isConnected).toBe(false);expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(question().value).toBe('Keep my exact Chief directions.');expect(task()).toBeUndefined();
 expect(document.activeElement).not.toBe(question());expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('opens the same retained Gmail task from Saved sources and returns to that origin',async()=>{
 await openChat();await type('Retain source-review directions.');await click('Details');await click('Choose notes or sources');await click('Saved sources');const opener=button('Review Gmail email');
 await click('Review Gmail email');await wait(()=>expect(task()).toBeDefined());const owner=host.querySelector('.google-message-panel');expect(owner).not.toBeNull();
 await click('‹ Back to saved sources');await wait(()=>expect(document.activeElement).toBe(opener));expect([...host.querySelectorAll('section[aria-label="Saved sources"]')].some(visible)).toBe(true);
 await click('Review Gmail email');expect(host.querySelectorAll('.google-message-panel')).toHaveLength(1);expect(host.querySelector('.google-message-panel')).toBe(owner);
 await click('‹ Back to saved sources');await click('‹ Back to Chief of Staff');expect(question().value).toBe('Retain source-review directions.');
});
it('reads and saves one reviewed Gmail source and prepares the existing Chief draft without sending',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChat();await type('Keep the existing clinic directions.');await readEmail();
 await wait(()=>expect(task()?.querySelector('pre')?.textContent).toBe(GMAIL_REHEARSAL_TEXT));await click('Use for current visit');await wait(()=>expect(task()?.querySelector<HTMLInputElement>('input[type="checkbox"]')).toBeTruthy());await wait(()=>expect(task()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Save reviewed email for this visit');await click('Prepare Chief draft');
 await wait(()=>expect(question().disabled).toBe(false));expect(question().value).toContain('Keep the existing clinic directions.');expect(question().value).toContain('Review the human-selected email source');expect(question().value).not.toContain(GMAIL_REHEARSAL_TEXT);expect(task()).toBeUndefined();
 expect(stats()).toMatchObject({lists:1,reads:1,reviews:1,externalCalls:0});expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 await openTask();await wait(()=>expect(document.activeElement).toBe(task()?.querySelector('h1')));expect(host.querySelectorAll('.google-message-panel')).toHaveLength(1);await click('Check email access');await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(button('Details')));expect(question().value).toContain('Keep the existing clinic directions.');expect(stats()).toMatchObject({lists:1,reads:1,reviews:1,inspects:1});
});
it('returns to Chief with a durable unconfirmed request and recovers the same key after remount',async()=>{
 history.replaceState(null,'','?scenario=gmail-unconfirmed-read#cosmas/home');await openChat();await type('Keep this draft through email recovery.');await readEmail();await click('Check saved email result');const request=stats().requests.find(r=>r.action==='read')!;
 expect(task()?.textContent).toContain('result is unconfirmed');await click('‹ Back to Chief of Staff');await wait(()=>expect(question().disabled).toBe(false));await type('Updated Chief directions while email remains unresolved.');await click('‹ Messages');
 await act(async()=>root.unmount());root=createRoot(host);await installFixtures();history.replaceState(null,'','?scenario=gmail-unconfirmed-read#cosmas/home');await mount();await openChat();expect(question().value).toBe('Updated Chief directions while email remains unresolved.');await openTask();
 await click('Restore saved email work');await click('Check saved email result');expect(stats()).toMatchObject({lists:0,reads:0,reviews:0,resolves:1});expect(stats().requests.find(r=>r.action==='resolve')?.key).toBe(request.key);await click('‹ Back to Chief of Staff');expect(question().value).toBe('Updated Chief directions while email remains unresolved.');
});
it('does not strand a delayed initial Gmail journal load when Back is followed by reopening',async()=>{
 await openChat();await type('Keep the draft during storage recovery.');const load=DraftJournal.prototype.load;let release!:(value:Awaited<ReturnType<typeof load>>)=>void,count=0;
 vi.spyOn(DraftJournal.prototype,'load').mockImplementation(function(this:DraftJournal,address){if(address===accountEditorAddress('google-messages')){count++;if(count===1)return new Promise(resolve=>{release=resolve;});}return load.call(this,address);});
 await click('Details');await click('Choose notes or sources');await click('Review Gmail email');await wait(()=>expect(release).toBeTypeOf('function'));await click('‹ Back to Chief of Staff');expect(question().value).toBe('Keep the draft during storage recovery.');await click('Details');await click('Choose notes or sources');await click('Review Gmail email');await act(async()=>release(null));
 await wait(()=>expect(button('Check email access')).toBeTruthy());await wait(()=>expect(button('Check email access')!.disabled).toBe(false));expect(count).toBe(1);expect(stats()).toMatchObject({lists:0,reads:0,reviews:0});expect(host.querySelectorAll('.google-message-panel')).toHaveLength(1);
});
it('restores the exact older reading position and current Details control without a new read mark',async()=>{
 await openChat();await type('Keep my place and draft.');vi.spyOn(HTMLElement.prototype,'scrollHeight','get').mockImplementation(function(this:HTMLElement){return this.classList.contains('mobile-chat-scroll')?1000:0;});vi.spyOn(HTMLElement.prototype,'clientHeight','get').mockImplementation(function(this:HTMLElement){return this.classList.contains('mobile-chat-scroll')?200:0;});
 const scroll=()=>host.querySelector<HTMLElement>('.mobile-chat-scroll')!;scroll().scrollTop=230;await act(async()=>scroll().dispatchEvent(new Event('scroll')));const mark=vi.spyOn(conversationsApi,'mark');await openTask();await click('‹ Back to Chief of Staff');
 await wait(()=>expect(scroll().scrollTop).toBe(230));await wait(()=>expect(document.activeElement).toBe(button('Details')));expect(question().value).toBe('Keep my place and draft.');expect(mark).not.toHaveBeenCalled();expect(stats()).toMatchObject({lists:0,reads:0,reviews:0});
});
it('cancels a deferred Gmail opening when Details is dismissed during authorization',async()=>{
 await openChat();await type('Keep the current draft.');await click('Details');await click('Choose notes or sources');const team=workspaceApi.team,prior=await team(identity);let finish!:(value:typeof prior)=>void;
 vi.spyOn(workspaceApi,'team').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await act(async()=>button('Review Gmail email')!.click());await wait(()=>expect(finish).toBeTypeOf('function'));await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));await act(async()=>finish(prior));expect(task()).toBeUndefined();expect(question().value).toBe('Keep the current draft.');expect(stats().reads).toBe(0);
});
it('ignores a retained Back callback after native suspend and resume',async()=>{
 const native={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000901',isCurrent:()=>true}};await act(async()=>root.render(<EncounterWorkspace authenticated={native} draftStorage={storage}/>));await openChat();await type('Retained native directions.');await openTask();
 let oldReturn:FrameRequestCallback|undefined;vi.spyOn(window,'requestAnimationFrame').mockImplementationOnce(callback=>{oldReturn=callback;return 100001;});await click('‹ Back to Chief of Staff');expect(oldReturn).toBeTypeOf('function');await act(async()=>notifyNativeWorkspaceForeground(native,false));await act(async()=>notifyNativeWorkspaceForeground(native,true));const target=button('Details')!;target.focus({preventScroll:true});const scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;scroll.scrollTop=83;
 await act(async()=>oldReturn!(0));expect(document.activeElement).toBe(target);await wait(()=>expect(scroll.scrollTop).toBe(83));expect(question().value).toBe('Retained native directions.');expect(stats().reads).toBe(0);
});

async function saveEmailForCard():Promise<GoogleMessageReviewResponse>{
 const review=vi.spyOn(googleMessageApi,'review');await readEmail();await click('Use for current visit');await wait(()=>expect(task()?.querySelector<HTMLInputElement>('input[type="checkbox"]')).toBeTruthy());await wait(()=>expect(task()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Save reviewed email for this visit');await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));return review.mock.results[0].value;
}
it.each([false,true])('opens a saved Gmail card and restores its exact source, draft and reading position without an added read mark (clamped=%s)',async clamped=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),marks=vi.spyOn(conversationsApi,'mark'),reads=vi.spyOn(conversationsApi,'read'),original='Keep these Chief directions while I inspect my saved Gmail email.';
 await openChat();await type(original);const receipt=await saveEmailForCard();let oldReturn:FrameRequestCallback|undefined;vi.spyOn(window,'requestAnimationFrame').mockImplementationOnce(callback=>{oldReturn=callback;return 100002;});await click('‹ Back to Chief of Staff');expect(oldReturn).toBeTypeOf('function');
 const card=host.querySelector<HTMLElement>(`[data-entry-id="source:${receipt.entry_id}"]`);expect(card).not.toBeNull();expect(card!.getAttribute('aria-label')).toBe('Saved Gmail email');expect(card!.textContent).toContain('Google message: Invented visit follow-up');expect(card!.textContent).not.toContain('sender@example.invalid');expect(card!.textContent).not.toContain(GMAIL_REHEARSAL_TEXT);expect(card!.querySelector('time')?.dateTime).toBe(receipt.workspace.entries.find(entry=>entry.id===receipt.entry_id)!.created_at);
 const control=card!.querySelector<HTMLButtonElement>('button')!,scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1100});
 if(clamped){
  // Clamping can reveal the latest reply. This case first acknowledges that
  // reply normally; the non-clamping case keeps the lower reply unread.
  scroll.scrollTop=900;await act(async()=>scroll.dispatchEvent(new Event('scroll')));await wait(()=>expect(marks.mock.calls.some(([, , ,command])=>command?.watermark!==undefined&&command.manual_unread===undefined)).toBe(true));await act(async()=>{await Promise.all(marks.mock.results.map(result=>result.value));});
 }
 const readState=await conversationsApi.read(identity,null);expect(readState.rows.find(row=>row.workspace_id===receipt.workspace.id&&row.bot.role==='chief')?.unread).toBe(!clamped);scroll.scrollTop=230;await act(async()=>scroll.dispatchEvent(new Event('scroll')));
 const before=structuredClone(stats()),markCount=marks.mock.calls.length,readCount=reads.mock.calls.length,turnIds=[...host.querySelectorAll('.team-turn')].map(entry=>entry.getAttribute('data-entry-id'));
 await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe(`source-${receipt.entry_id}`));const exact=document.getElementById(`source-${receipt.entry_id}`)!;expect(exact.classList.contains('selected')).toBe(true);expect(exact.querySelector(':scope > p')?.textContent).toBe(GMAIL_REHEARSAL_TEXT);expect(question().value).toBe(original);
 if(clamped)Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:375});await click('‹ Back to Chief of Staff');await act(async()=>oldReturn!(0));await wait(()=>expect(document.activeElement).toBe(control));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(document.activeElement).not.toBe(question());await wait(()=>expect(scroll.scrollTop).toBe(clamped?175:230));expect(question().value).toBe(original);
 expect([...host.querySelectorAll('.team-turn')].map(entry=>entry.getAttribute('data-entry-id'))).toEqual(turnIds);expect(host.querySelector('.messages-new-replies')).toBeNull();expect(stats()).toEqual(before);expect(marks).toHaveBeenCalledTimes(markCount);expect(reads).toHaveBeenCalledTimes(readCount);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('opens an unavailable saved Gmail card with only generic metadata and the existing source placeholder',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),original='Keep these directions when the saved Gmail source is unavailable.';await openChat();await type(original);const receipt=await saveEmailForCard();await click('Prepare Chief draft');await wait(()=>expect(question().value).toContain(original));const retained=question().value;
 await act(async()=>{(window as Window&{gmailRehearsalControls?:{disconnect:()=>void}}).gmailRehearsalControls!.disconnect();});await click('‹ Messages');await openChat();const card=()=>host.querySelector<HTMLElement>(`[data-entry-id="source:${receipt.entry_id}"]`);await wait(()=>expect(card()?.querySelector('h3')?.textContent).toBe('Unavailable email source'));expect(card()!.getAttribute('aria-label')).toBe('Saved Gmail email');expect(card()!.textContent).not.toContain('Invented visit follow-up');expect(card()!.textContent).not.toContain(GMAIL_REHEARSAL_TEXT);expect(card()!.textContent).toContain('Unavailable — check access');
 const before=structuredClone(stats()),control=card()!.querySelector<HTMLButtonElement>('button')!;await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe(`source-${receipt.entry_id}`));const exact=document.getElementById(`source-${receipt.entry_id}`)!;expect(exact.textContent).toContain('This email source is unavailable');expect(exact.textContent).not.toContain('Invented visit follow-up');expect(exact.textContent).not.toContain(GMAIL_REHEARSAL_TEXT);await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));expect(question().value).toBe(retained);expect(stats()).toEqual(before);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});