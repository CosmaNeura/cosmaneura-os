import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED','VITE_MICROSOFT_MESSAGE_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {openDraftStore} from './draft-store';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement,idb:IDBFactory;
const storage=({scope}:{scope:string})=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const task=()=>[...host.querySelectorAll<HTMLElement>('[aria-label="Review Outlook email"]')].find(visible);
const stats=()=> (window as Window&{outlookRehearsalStats?:{reads:number;reviews:number;resolves:number;inspects:number;requests:{action:string;key:string|null}[]}}).outlookRehearsalStats!;
async function wait(check:()=>void){for(let n=0;n<500;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>button(name)!.click());}
async function type(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openChat(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()?.disabled).toBe(false));}
async function openTask(){await click('Details');await click('Review Outlook email');await wait(()=>expect(task()).toBeDefined());await wait(()=>expect((button('Check email access')??button('Restore saved email work'))?.disabled).toBe(false));}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('uses one retained Outlook owner from Chief and sources, then appends a reviewed email to the actual retained Chief draft',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChat();await type('Keep my exact invented Chief directions.');await openTask();
 expect(host.querySelectorAll('.outlook-message-panel')).toHaveLength(1);expect(stats().reads).toBe(0);
 await click('‹ Back to Chief of Staff');expect(question().value).toBe('Keep my exact invented Chief directions.');await openTask();
 await click('Check email access');await click('Select email');const selected=()=>task()!.querySelector<HTMLButtonElement>('.outlook-message-list button')!;await wait(()=>expect(selected()?.disabled).toBe(false));await act(async()=>selected().click());
 await click('Read full email');await wait(()=>expect(task()?.textContent).toContain('Invented message for Jordan Cypress'));
 await click('Use for current visit');const checkbox=()=>task()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!;await wait(()=>expect(checkbox()?.disabled).toBe(false));await act(async()=>checkbox().click());
 await click('Save reviewed email for this visit');await wait(()=>expect(button('Prepare Chief draft')?.disabled).toBe(false));expect(stats().reads).toBe(2);expect(stats().reviews).toBe(1);
 await click('Prepare Chief draft');await wait(()=>expect(question().disabled).toBe(false));expect(question().value).toContain('Keep my exact invented Chief directions.');expect(question().value).toContain('Review the human-selected email source');expect(task()).toBeUndefined();
 expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 await click('Details');await click('Saved sources');await click('Review Outlook email');await wait(()=>expect(task()).toBeDefined());expect(host.querySelectorAll('.outlook-message-panel')).toHaveLength(1);expect(stats().reads).toBe(2);await click('‹ Back to saved sources');
 expect([...host.querySelectorAll('[aria-label="Scribe sources"]')].find(visible)?.textContent).toContain('Invented message for Jordan Cypress');expect(ask).not.toHaveBeenCalled();
});
it('resolves a lost body result after reload with the same encrypted command and no additional Outlook read',async()=>{
 history.replaceState(null,'','?scenario=outlook-lost-read#cosmas/home');await openChat();await type('Retain these invented directions through reload.');await openTask();await click('Check email access');await click('Select email');
 await wait(()=>expect(task()!.querySelector<HTMLButtonElement>('.outlook-message-list button')?.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('.outlook-message-list button')!.click());await click('Read full email');await wait(()=>expect(button('Check saved email result')?.disabled).toBe(false));
 const before=stats(),request=before.requests.find(item=>item.action==='read')!;expect(before.reads).toBe(2);
 await act(async()=>root.unmount());root=createRoot(host);await installFixtures();history.replaceState(null,'','?scenario=outlook-lost-read#cosmas/home');await mount();await openChat();expect(question().value).toBe('Retain these invented directions through reload.');await openTask();
 await click('Restore saved email work');await click('Check saved email result');await wait(()=>expect(task()?.textContent).toContain('Invented message for Jordan Cypress'));
 expect(stats().reads).toBe(0);expect(stats().resolves).toBe(1);expect(stats().requests.find(item=>item.action==='resolve')?.key).toBe(request.key);
});
it('does not open Outlook after Details is dismissed during its final account authorization',async()=>{
 await openChat();await type('Keep this draft.');await click('Details');const team=workspaceApi.team;let finish!:(value:Awaited<ReturnType<typeof team>>)=>void;
 const prior=await team(identity);vi.spyOn(workspaceApi,'team').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await act(async()=>button('Review Outlook email')!.click());await wait(()=>expect(finish).toBeDefined());await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 await act(async()=>finish(prior));expect(task()).toBeUndefined();expect(question().value).toBe('Keep this draft.');expect(stats().reads).toBe(0);
});
it('chooses an existing visit from Microsoft settings while retaining the read and requiring a fresh visit check',async()=>{
 await click('Settings');const card=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('.settings-card')].find(b=>visible(b)&&b.querySelector('strong')?.textContent===label);
 await wait(()=>expect(card('Connections')?.disabled).toBe(false));await act(async()=>card('Connections')!.click());await wait(()=>expect(card('Microsoft email & calendar')?.disabled).toBe(false));await act(async()=>card('Microsoft email & calendar')!.click());
 await click('Work with email');await click('Check email access');await click('Select email');await wait(()=>expect(task()?.querySelector<HTMLButtonElement>('.outlook-message-list button')?.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('.outlook-message-list button')!.click());await click('Read full email');
 await click('Choose a visit');const visit=()=>[...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(visible);await wait(()=>expect(visit()?.disabled).toBe(false));await act(async()=>visit()!.click());
 await wait(()=>expect(task()).toBeDefined());await click('Restore saved email work');expect(button('Use for current visit')?.disabled??true).toBe(true);await click('Check email access');await click('Use for current visit');
 await wait(()=>expect(task()?.textContent).toContain('Visit confirmed: Jordan Cypress'));expect(stats().reads).toBe(2);expect(stats().inspects).toBe(1);expect(stats().reviews).toBe(0);expect(host.querySelectorAll('.outlook-message-panel')).toHaveLength(1);
});
it('cancels a deferred task opening on native suspend without discarding the Chief draft',async()=>{
 const native={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000901',isCurrent:()=>true}};
 await act(async()=>root.render(<EncounterWorkspace authenticated={native} draftStorage={storage}/>));await openChat();await type('Keep native draft.');await click('Details');const team=workspaceApi.team,prior=await team(native);let finish!:(value:typeof prior)=>void;
 vi.spyOn(workspaceApi,'team').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await act(async()=>button('Review Outlook email')!.click());await wait(()=>expect(finish).toBeDefined());
 await act(async()=>notifyNativeWorkspaceForeground(native,false));await act(async()=>finish(prior));expect(task()).toBeUndefined();expect(question().value).toBe('Keep native draft.');expect(stats().reads).toBe(0);await act(async()=>notifyNativeWorkspaceForeground(native,true));
});
it('returns from an unconfirmed read to type in Chief and reopens the same pending request without repeating it',async()=>{
 history.replaceState(null,'','?scenario=outlook-unconfirmed-read#cosmas/home');await openChat();await type('Chief directions before email.');await openTask();await click('Check email access');await click('Select email');
 await wait(()=>expect(task()?.querySelector<HTMLButtonElement>('.outlook-message-list button')?.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('.outlook-message-list button')!.click());await click('Read full email');await click('Check saved email result');
 await wait(()=>expect(task()?.textContent).toContain('its result is unconfirmed'));const request=stats().requests.find(item=>item.action==='read')!,reads=stats().reads;
 await click('‹ Back to Chief of Staff');await wait(()=>expect(question().disabled).toBe(false));expect(question().value).toBe('Chief directions before email.');await type('Chief directions edited while email stays unresolved.');
 await click('‹ Messages');await openChat();expect(question().value).toBe('Chief directions edited while email stays unresolved.');await click('Details');await click('Review Outlook email');await wait(()=>expect(button('Check saved email result')?.disabled).toBe(false));
 await click('Check saved email result');expect(stats().reads).toBe(reads);expect(stats().requests.filter(item=>item.action==='resolve').every(item=>item.key===request.key)).toBe(true);expect(stats().reviews).toBe(0);
});
