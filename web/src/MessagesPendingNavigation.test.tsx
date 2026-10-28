import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
const observed=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null}));
vi.mock('./session/use-workspace-session',async original=>{const value=await original<typeof import('./session/use-workspace-session')>();return {...value,useWorkspaceSession:(...args:Parameters<typeof value.useWorkspaceSession>)=>{observed.session=args[0];return value.useWorkspaceSession(...args);}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {modelWorkApi} from './model-work-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(control=>visible(control)&&(control.textContent?.trim()===name||control.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
async function ready(check:()=>void){await vi.waitFor(async()=>{await act(async()=>{});check();});}
async function click(name:string){await ready(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>button(name)!.click());}
async function text(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openChief(){await ready(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await ready(()=>expect(question()?.disabled).toBe(false));}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));await openChief();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it.each(['in-flight','unconfirmed'] as const)('keeps the exact %s message beside recovery when visible Messages Back is pressed, then allows navigation after confirmation',async phase=>{
 const original=workspaceApi.ask;
 let receipt:Awaited<ReturnType<typeof workspaceApi.ask>>|undefined,release:(()=>void)|undefined;
 const ask=vi.spyOn(workspaceApi,'ask').mockImplementation(async(...args)=>{
  const saved=await original(...args);receipt=saved;
  if(phase==='unconfirmed')throw new WorkspaceApiError(503);
  await new Promise<void>(resolve=>{release=resolve;});return saved;
 });
 const resolve=vi.spyOn(modelWorkApi,'resolve').mockImplementation(async(_owner,_workspace,operation)=>{
  expect(operation).toEqual(observed.session!.getSnapshot().pending);expect(receipt).toBeDefined();return receipt!;
 });
 const composer=question();await text('Invented exact request retained while returning.');await click('Send message');
 await ready(()=>expect(receipt).toBeDefined());
 if(phase==='unconfirmed')await ready(()=>expect(observed.session!.getSnapshot().busy).toBe(false));
 const before=location.hash,pending=structuredClone(observed.session!.getSnapshot().pending),draft=composer.value;
 expect(pending?.type).toBe('ask');await click('‹ Messages');
 expect(location.hash).toBe(before);expect(host.querySelector('.messages-inbox')).toBeNull();
 expect(observed.session!.getSnapshot().practicePage).toBe('notebook');expect(observed.session!.getSnapshot().pending).toEqual(pending);
 expect(question()).toBe(composer);expect(composer.value).toBe(draft);expect(host.textContent).toContain('Finish or check the current action before going back. Your text is retained.');
 if(phase==='in-flight'){expect(release).toBeTypeOf('function');await act(async()=>release!());}
 else await click(button('Check message')?'Check message':'Check saved result');
 await ready(()=>expect(observed.session!.getSnapshot().pending).toBeNull());await ready(()=>expect(question().disabled).toBe(false));
 await text('Keep this next unsent Chief draft.');await click('‹ Messages');await ready(()=>expect(host.querySelector('.messages-inbox')).not.toBeNull());
 await openChief();expect(question().value).toBe('Keep this next unsent Chief draft.');expect(ask).toHaveBeenCalledOnce();
 expect(resolve).toHaveBeenCalledTimes(phase==='unconfirmed'?1:0);
});
