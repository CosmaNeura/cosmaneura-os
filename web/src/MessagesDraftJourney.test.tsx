import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {openDraftStore} from './draft-store';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement,idb:IDBFactory;
const storage=({scope}:{scope:string})=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));
async function wait(check:()=>void){for(let n=0;n<400;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>button(name)!.click());}
async function openChat(){await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()?.disabled).toBe(false));}
async function type(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await wait(()=>expect(row()).toBeDefined());}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('shows an encrypted retained draft after returning to Chats and reloading, then removes its marker after clearing',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChat();await type('Invented private directions retained only on this device.');await click('‹ Messages');
 await wait(()=>expect(row()?.querySelector('[data-draft-presence]')?.textContent).toBe('Draft'));
 expect(row()?.textContent).not.toContain('Invented private directions');expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 await act(async()=>root.unmount());root=createRoot(host);history.replaceState(null,'','#cosmas/home');await mount();
 await wait(()=>expect(row()?.querySelector('[data-draft-presence]')?.textContent).toBe('Draft'));await openChat();
 expect(question().value).toBe('Invented private directions retained only on this device.');await type('');await click('‹ Messages');
 await wait(()=>expect(row()?.querySelector('[data-draft-presence]')).toBeNull());expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('removes the retained draft marker only after the scripted send is confirmed, including after reload',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask');await openChat();await type('Invented question for the scripted usability fixture.');await click('‹ Messages');
 await wait(()=>expect(row()?.querySelector('[data-draft-presence]')?.textContent).toBe('Draft'));await openChat();
 await click('Send message');await wait(()=>expect(ask).toHaveBeenCalledOnce());await wait(()=>expect(question().value).toBe(''));
 await click('‹ Messages');await wait(()=>expect(row()?.querySelector('[data-draft-presence]')).toBeNull());
 await act(async()=>root.unmount());root=createRoot(host);history.replaceState(null,'','#cosmas/home');await mount();
 await wait(()=>expect(row()?.querySelector('[data-draft-presence]')).toBeNull());await openChat();expect(question().value).toBe('');expect(ask).toHaveBeenCalledOnce();
});
