import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {PreviewSession} from '../ux-acceptance/PreviewSession';
import {previewSession,createPreviewSession,PREVIEW_SIGNED_OUT_KEY} from '../ux-acceptance/preview-session';
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
async function wait(check:()=>void){for(let n=0;n<300;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>button(name)!.click());}
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question');
async function openChat(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()?.disabled).toBe(false));}
async function mount(session=previewSession){await act(async()=>root.render(<PreviewSession session={session}>{(owner,controls)=><EncounterWorkspace authenticated={owner} accountControls={controls} draftStorage={storage}/>}</PreviewSession>));}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();localStorage.clear();sessionStorage.clear();previewSession.close(false);previewSession.enter();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();previewSession.close(false);vi.restoreAllMocks();vi.unstubAllGlobals();});
it('closes from Settings, survives a fresh controller, and requires explicit Continue preview',async()=>{
 await mount();await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());await click('Settings');
 const logout=host.querySelector<HTMLButtonElement>('.settings-hub [aria-label="Account"] button');expect(logout?.textContent).toBe('Log out');const old=identity;
 await act(async()=>logout!.click());expect(host.querySelector('.team-workspace')).toBeNull();expect(host.textContent).toContain('Preview is closed');expect(await old.getToken({skipCache:true})).toBeNull();
 expect(localStorage.getItem(PREVIEW_SIGNED_OUT_KEY)).toBe('closed');
 await act(async()=>root.unmount());root=createRoot(host);const restarted=createPreviewSession(localStorage,false);const reads=vi.spyOn(workspaceApi,'team');await mount(restarted);
 expect(reads).not.toHaveBeenCalled();expect(host.querySelector('.team-workspace')).toBeNull();await click('Continue preview');await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());expect(reads).toHaveBeenCalled();
});
it('keeps the encrypted Chief draft for explicit recovery after logout and entry without sending',async()=>{
 await mount();await openChat();const draft='Keep these unsent directions across preview logout.';
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),draft);question()!.dispatchEvent(new Event('input',{bubbles:true}));});
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await click('‹ Messages');await click('Settings');await click('Log out');
 expect(host.textContent).not.toContain(draft);await click('Continue preview');await openChat();
 expect(question()?.value).toBe(draft);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('a late old-owner startup response cannot reopen the signed-out view',async()=>{
 let finish!:(value:Awaited<ReturnType<typeof workspaceApi.team>>)=>void;const team=await workspaceApi.team(identity);vi.spyOn(workspaceApi,'team').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await mount();await wait(()=>expect(finish).toBeTypeOf('function'));await act(async()=>previewSession.close());await act(async()=>finish(team));
 expect(host.querySelector('.team-workspace')).toBeNull();expect(host.textContent).not.toContain('Jordan');expect(host.textContent).toContain('Preview is closed');
});
