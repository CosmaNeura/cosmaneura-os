import {act} from 'react';
import {waitMessagesJourney as wait, MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_EHR_READ_ENABLED','VITE_CALENDAR_IMPORT_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {openDraftStore} from './draft-store';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {researchApi} from './research-api';
import type {ResearchSaved} from './research-contract';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import {conversationsApi} from './conversations-api';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');

// Journey waits may legitimately exceed Vitest's 5s default under CI load.
vi.setConfig({testTimeout: MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement,idb:IDBFactory,owner:AuthenticatedWorkspaceIdentity;
const storage=({scope}:{scope:string})=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(element=>visible(element)&&(element.textContent?.trim()===name||element.getAttribute('aria-label')===name));
const composer=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const research=()=>[...host.querySelectorAll<HTMLElement>('.research-workspace')].find(visible);
const query=()=>research()?.querySelector<HTMLTextAreaElement>('.research-question textarea');
const stats=()=>(window as Window&{researchRehearsalStats?:{searches:number;saves:number;resolveSearches:number;resolveSaves:number;historyReads:number;packetReads:number;externalCalls:number}}).researchRehearsalStats!;
const publicQuestion='What does public evidence say about sleep diaries for adults with insomnia?';
function noDispatchReceipt(){for(const key of Object.keys(sessionStorage).filter(key=>key.endsWith(':receipts')))expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual([]);}
async function click(name:string){await wait(()=>expect(button(name)).toBeTruthy());await wait(()=>expect(button(name)!.disabled).toBe(false));await act(async()=>button(name)!.click());}
async function type(element:HTMLTextAreaElement,value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(element,value);element.dispatchEvent(new Event('input',{bubbles:true}));});}
async function checkLabel(text:string){const box=()=>[...research()!.querySelectorAll<HTMLLabelElement>('label')].find(label=>label.textContent?.includes(text))?.querySelector<HTMLInputElement>('input[type="checkbox"]');await wait(()=>expect(box()).toBeTruthy());await wait(()=>expect(box()!.disabled).toBe(false));await act(async()=>box()!.click());}
async function openChief(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(element=>visible(element)&&element.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()).toBeTruthy());await wait(()=>expect(row()!.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(composer()).toBeTruthy());await wait(()=>expect(composer()!.disabled).toBe(false));}
async function chooseResearch(){
 await click('New message');const choice=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-bot-choices button')].find(element=>element.querySelector('strong')?.textContent==='Research');await wait(()=>expect(choice()).toBeTruthy());await wait(()=>expect(choice()!.disabled).toBe(false));await act(async()=>choice()!.click());
 const visit=()=>[...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(visible);await wait(()=>expect(visit()).toBeTruthy());await wait(()=>expect(visit()!.disabled).toBe(false));expect(visit()?.textContent).toContain('Jordan Cypress');await act(async()=>visit()!.click());await wait(()=>expect(research()).toBeDefined());
}
async function searchAndSave(){
 await wait(()=>expect(query()).toBeTruthy());await wait(()=>expect(query()!.disabled).toBe(false));await type(query()!,publicQuestion);await checkLabel('PubMed');await click('Review query');await checkLabel('This is a general public question');await click('Search selected sources');
 await wait(()=>expect(research()?.textContent).toContain('Invented source excerpt. Not clinical evidence.'));await checkLabel('Select excerpt to save');await click('Save selected excerpts');
}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={owner} draftStorage={storage}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());}
async function remount(){await act(async()=>root.unmount());root=createRoot(host);await installFixtures();history.replaceState(null,'',location.search+'#cosmas/home');await mount();}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 owner=identity;idb=new IDBFactory();localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it('keeps the actual Chief prefix and prepares only a saved-packet reference, without another search, save or model dispatch',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),save=vi.spyOn(researchApi,'save'),prefix='Keep my exact original Chief directions.';
 await openChief();await type(composer(),prefix);await click('‹ Messages');await chooseResearch();await searchAndSave();await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));
 const receipt=await save.mock.results[0].value as ResearchSaved,before=structuredClone(stats());expect(before).toMatchObject({searches:1,saves:1,externalCalls:0});
 await click('Prepare Chief draft');await wait(()=>expect(composer().value).toContain('Review the saved public Research packet'));
 expect(composer().value.startsWith(prefix+'\n\n')).toBe(true);expect(composer().value).toContain(receipt.entry_id);expect(composer().value).toContain(`revision ${receipt.entry_revision}`);
 expect(composer().value).not.toContain('Invented source excerpt');expect(composer().value).not.toContain('pubmed.ncbi.nlm.nih.gov');expect(composer().value).not.toContain(publicQuestion);expect(document.activeElement).toBe(composer());
 expect(stats()).toEqual(before);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();noDispatchReceipt();expect(research()).toBeUndefined();
 await click('‹ Messages');await chooseResearch();await click('Restore research draft');expect(query()?.value).toBe(publicQuestion);expect(stats().searches).toBe(1);expect(stats().saves).toBe(1);
});

it('restores an unconfirmed evidence save from encrypted storage after real unmount and resolves its exact request without repeating lookup or save',async()=>{
 history.replaceState(null,'','?research-scenario=lost-save-reply#cosmas/home');
 const prefix='Retain this exact Chief draft across the lost Research save.',save=vi.spyOn(researchApi,'save');await openChief();await type(composer(),prefix);await click('‹ Messages');await chooseResearch();await searchAndSave();
 await wait(()=>expect(button('Check saved result')).toBeTruthy());await wait(()=>expect(button('Check saved result')!.disabled).toBe(false));const call=save.mock.calls[0],request=structuredClone(call[3]),run=call[2];expect(stats()).toMatchObject({searches:1,saves:1});
 await remount();const resolve=vi.spyOn(researchApi,'resolveSave'),ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');
 await openChief();expect(composer().value).toBe(prefix);await click('‹ Messages');await chooseResearch();await click('Restore research draft');expect(query()?.value).toBe(publicQuestion);
 await click('Check saved result');await wait(()=>expect(button('Load saved source details for Chief')).toBeTruthy());await wait(()=>expect(button('Load saved source details for Chief')!.disabled).toBe(false));expect(resolve).toHaveBeenCalledTimes(1);expect(resolve.mock.calls[0][2]).toBe(run);expect(resolve.mock.calls[0][3]).toEqual(request);expect(stats()).toMatchObject({searches:0,saves:0,resolveSaves:1});
 await click('Load saved source details for Chief');await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));const before=structuredClone(stats());await click('Prepare Chief draft');await wait(()=>expect(composer().value).toContain('Review the saved public Research packet'));
 expect(composer().value.startsWith(prefix+'\n\n')).toBe(true);expect(composer().value).not.toContain('Invented source excerpt');expect(stats()).toEqual(before);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();noDispatchReceipt();
});

it('does not append or focus a Chief continuation when native foreground is lost during mounted account authorization',async()=>{
 owner={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000991',isCurrent:()=>true}};await act(async()=>root.render(<EncounterWorkspace authenticated={owner} draftStorage={storage}/>));
 const prefix='Keep my native Chief draft unchanged.',ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChief();await type(composer(),prefix);await click('‹ Messages');await chooseResearch();await searchAndSave();await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));
 const prior=await workspaceApi.team(owner);let finish!:(value:typeof prior)=>void;vi.spyOn(workspaceApi,'team').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));const before=structuredClone(stats());
 await act(async()=>button('Prepare Chief draft')!.click());await wait(()=>expect(finish).toBeDefined());await act(async()=>notifyNativeWorkspaceForeground(owner,false));await act(async()=>finish(prior));
 expect(composer().value).not.toContain('Review the saved public Research packet');expect(document.activeElement).not.toBe(composer());expect(stats()).toEqual(before);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();noDispatchReceipt();await act(async()=>notifyNativeWorkspaceForeground(owner,true));
 await remount();await openChief();expect(composer().value).toBe(prefix);
},MESSAGES_JOURNEY_TEST_TIMEOUT_MS);

it.each([false,true])('opens a saved Research packet in Chief and returns to its exact card without draft, scroll, keyboard or readmark changes (native=%s)',async native=>{
 if(native){owner={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000992',isCurrent:()=>true}};await act(async()=>root.render(<EncounterWorkspace authenticated={owner} draftStorage={storage}/>));}
 const prefix='Keep my exact original Chief directions while I inspect research.',ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),save=vi.spyOn(researchApi,'save'),marks=vi.spyOn(conversationsApi,'mark'),reads=vi.spyOn(conversationsApi,'read');
 await openChief();await type(composer(),prefix);await click('‹ Messages');await chooseResearch();await searchAndSave();await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));expect([...host.querySelectorAll('.conversation-material-card')].filter(visible)).toHaveLength(0);const receipt=await save.mock.results[0].value as ResearchSaved;
 await click('Prepare Chief draft');await wait(()=>expect(composer().value).toContain('Review the saved public Research packet'));const draft=composer().value;expect(draft.startsWith(prefix+'\n\n')).toBe(true);const card=host.querySelector<HTMLElement>(`[data-entry-id="source:${receipt.entry_id}"]`)!,control=card.querySelector<HTMLButtonElement>('button')!;expect(card.getAttribute('aria-label')).toBe('Saved Research packet');expect(card.textContent).toContain('Research · public source excerpts');expect(card.querySelector('time')?.dateTime).toBeTruthy();expect(card.textContent).not.toContain('Invented source excerpt');expect(card.textContent).not.toContain(publicQuestion);expect(card.textContent).not.toContain('pubmed.ncbi.nlm.nih.gov');expect(host.querySelector('.team-conversation-empty')).toBeNull();
 const scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1100});scroll.scrollTop=230;await act(async()=>scroll.dispatchEvent(new Event('scroll')));const before=structuredClone(stats()),markCount=marks.mock.calls.length,readCount=reads.mock.calls.length;
 await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe('source-'+receipt.entry_id));const shown=document.getElementById('source-'+receipt.entry_id)!;expect(shown.classList.contains('selected')).toBe(true);expect(shown.textContent).toContain('Saved public Research snapshot · source claims require review');expect(shown.textContent).toContain('Invented source excerpt. Not clinical evidence.');expect(shown.textContent).not.toContain('Reference note · entered by you, unverified');expect(composer().value).toBe(draft);expect(stats()).toEqual(before);
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(document.activeElement).not.toBe(composer());await wait(()=>expect(scroll.scrollTop).toBe(230));expect(composer().value).toBe(draft);expect(host.querySelector('.messages-new-replies')).toBeNull();expect(stats()).toEqual(before);expect(marks).toHaveBeenCalledTimes(markCount);expect(reads).toHaveBeenCalledTimes(readCount);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();noDispatchReceipt();
});

it('prevents an older EHR task return from stealing focus after Research source navigation has completed',async()=>{
 owner={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000993',isCurrent:()=>true}};await act(async()=>root.render(<EncounterWorkspace authenticated={owner} draftStorage={storage}/>));
 await openChief();await type(composer(),'Keep the newer Research source focus and this Chief draft.');await click('‹ Messages');await chooseResearch();await searchAndSave();await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));await click('Prepare Chief draft');await wait(()=>expect(composer().value).toContain('Review the saved public Research packet'));const draft=composer().value;
 await click('Details');await click('Choose notes or sources');await click('Review EHR records');await wait(()=>expect(button('Check Elation access')).toBeDefined());let oldReturn:FrameRequestCallback|undefined;vi.spyOn(window,'requestAnimationFrame').mockImplementationOnce(callback=>{oldReturn=callback;return 11001;});await click('‹ Back to Chief of Staff');await wait(()=>expect(oldReturn).toBeTypeOf('function'));
 const card=host.querySelector<HTMLElement>('.conversation-material-card')!,control=card.querySelector<HTMLButtonElement>('button')!,id=card.dataset.entryId!.slice('source:'.length),scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1000});scroll.scrollTop=180;await act(async()=>scroll.dispatchEvent(new Event('scroll')));const before=structuredClone(stats());
 await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe('source-'+id));await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));await act(async()=>oldReturn!(0));expect(document.activeElement).toBe(control);expect(document.activeElement).not.toBe(composer());await wait(()=>expect(scroll.scrollTop).toBe(180));expect(composer().value).toBe(draft);expect(stats()).toEqual(before);expect((window as Window&{ehrRehearsalStats?:{reads:number;externalCalls:number}}).ehrRehearsalStats).toMatchObject({reads:0,externalCalls:0});noDispatchReceipt();
});

it.each(['direct','ehr','calendar'] as const)('keeps a Research source return 21px above the bottom through queued scroll and resize work (%s)',async nested=>{
 const observers:{callback:()=>void;element?:Element}[]=[];
 vi.stubGlobal('ResizeObserver',class{entry:{callback:()=>void;element?:Element};constructor(callback:()=>void){this.entry={callback};observers.push(this.entry);}observe(element:Element){this.entry.element=element;}disconnect(){}});
 owner={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000994',isCurrent:()=>true}};await act(async()=>root.render(<EncounterWorkspace authenticated={owner} draftStorage={storage}/>));
 const ask=vi.spyOn(workspaceApi,'ask'),marks=vi.spyOn(conversationsApi,'mark');
 await openChief();await type(composer(),'Keep my reading position and this Chief draft.');await click('‹ Messages');await chooseResearch();await searchAndSave();await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(button('Prepare Chief draft')!.disabled).toBe(false));await click('Prepare Chief draft');await wait(()=>expect(composer().value).toContain('Review the saved public Research packet'));
 const draft=composer().value,control=host.querySelector<HTMLButtonElement>('.conversation-material-card button')!,scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!,observer=observers.filter(item=>item.element===scroll).at(-1)!;
 expect(observer).toBeDefined();Object.defineProperty(scroll,'clientHeight',{configurable:true,value:149});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:3593});scroll.scrollTop=3423;await act(async()=>scroll.dispatchEvent(new Event('scroll')));const before=structuredClone(stats()),markCount=marks.mock.calls.length;
 await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toMatch(/^source-/));
 if(nested!=='direct'){
   const action=nested==='ehr'?'Review EHR records':'Import calendar file';scroll.scrollTop=71;await act(async()=>{scroll.dispatchEvent(new Event('scroll'));button(action)!.focus();});await click(action);await wait(()=>expect(button(nested==='ehr'?'Check Elation access':'Check import access')).toBeDefined());
   scroll.scrollTop=113;await click('‹ Back to saved sources');await wait(()=>expect(document.activeElement?.closest(nested==='ehr'?'.ehr-source-action':'.calendar-import-action')).not.toBeNull());await act(async()=>{scroll.dispatchEvent(new Event('scroll'));observer.callback();});await wait(()=>expect(scroll.scrollTop).toBe(71));
 }
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));
 await act(async()=>{scroll.dispatchEvent(new Event('scroll'));observer.callback();scroll.dispatchEvent(new Event('scroll'));observer.callback();});
 await wait(()=>expect(scroll.scrollTop).toBe(3423));expect(document.activeElement).toBe(control);expect(composer().value).toBe(draft);expect(stats()).toEqual(before);expect(marks).toHaveBeenCalledTimes(markCount);expect(ask).not.toHaveBeenCalled();noDispatchReceipt();
});