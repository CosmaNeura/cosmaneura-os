import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_EHR_READ_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
const observed=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null}));
vi.mock('./session/use-workspace-session',async original=>{const value=await original<typeof import('./session/use-workspace-session')>();return {...value,useWorkspaceSession:(...args:Parameters<typeof value.useWorkspaceSession>)=>{observed.session=args[0];return value.useWorkspaceSession(...args);}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi} from './workspace-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const sourceId='00000000-0000-4000-8000-000000009899';
let host:HTMLDivElement,root:Root,documentTop:number,documentLeft:number,documentHeight:number;
const originalScrolling=Object.getOwnPropertyDescriptor(document,'scrollingElement');
const rootDescriptors=new Map(['clientHeight','scrollHeight','clientWidth','scrollWidth','scrollTop','scrollLeft'].map(key=>[key,Object.getOwnPropertyDescriptor(document.documentElement,key)]));
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const composer=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
async function wait(check:()=>void){for(let i=0;i<350;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>{button(name)!.focus();button(name)!.click();});}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()});vi.stubGlobal('innerWidth',1280);vi.stubGlobal('innerHeight',900);window.scrollTo=vi.fn();
 documentTop=0;documentLeft=0;documentHeight=2400;
 Object.defineProperty(document,'scrollingElement',{configurable:true,value:document.documentElement});
 Object.defineProperties(document.documentElement,{clientHeight:{configurable:true,get:()=>900},scrollHeight:{configurable:true,get:()=>documentHeight},clientWidth:{configurable:true,get:()=>1280},scrollWidth:{configurable:true,get:()=>1280},scrollTop:{configurable:true,get:()=>documentTop,set:(value:number)=>{documentTop=Math.max(0,Math.min(value,documentHeight-900));}},scrollLeft:{configurable:true,get:()=>documentLeft,set:(value:number)=>{documentLeft=value;}}});
 // The real browser's source-task layout/scrollIntoView changes the document
 // while the desktop conversation's inner scroll remains zero.
 HTMLElement.prototype.scrollIntoView=vi.fn(function(this:HTMLElement){if(this.id===`source-${sourceId}`)document.documentElement.scrollTop=0;});
 await installFixtures(true);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await wait(()=>expect(composer()?.disabled).toBe(false));
 const w=structuredClone(observed.session!.getSnapshot().workspace!);w.revision++;w.entries.push({id:sourceId,revision:w.revision,kind:'ehr_read_source',source_label:'Athena: reviewed allergy records',ehr_source_state:'current',content:'Invented exact recorded allergy source; current status is not established.',origin:'authenticated_human',ticket:null,created_at:'2026-10-26T12:00:02Z'});
 vi.spyOn(workspaceApi,'read').mockResolvedValue(w);
 await act(async()=>observed.session!.setWorkspace(w));
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(composer(),'Keep my desktop Chief draft and reading position.');composer().dispatchEvent(new Event('input',{bubbles:true}));});
 const inner=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(inner,'clientHeight',{configurable:true,value:1187});Object.defineProperty(inner,'scrollHeight',{configurable:true,value:1187});inner.scrollTop=0;
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();for(const [key,descriptor]of rootDescriptors){if(descriptor)Object.defineProperty(document.documentElement,key,descriptor);else Reflect.deleteProperty(document.documentElement,key);}if(originalScrolling)Object.defineProperty(document,'scrollingElement',originalScrolling);else Reflect.deleteProperty(document,'scrollingElement');vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
async function openSource(){const control=host.querySelector<HTMLButtonElement>(`[data-entry-id="source:${sourceId}"] button`)!;document.documentElement.scrollTop=693;await act(async()=>{control.focus({preventScroll:true});control.click();});await wait(()=>expect(document.activeElement?.id).toBe(`source-${sourceId}`));expect(documentTop).toBe(0);return control;}

it.each(['direct','clamped','nested-task'] as const)('restores actual desktop document reading position on exact-source Back (%s)',async mode=>{
 const control=await openSource();
 if(mode==='nested-task'){await click('Review EHR records');await wait(()=>expect(button('Check Elation access')).toBeDefined());document.documentElement.scrollTop=125;await click('‹ Back to saved sources');await wait(()=>expect(document.activeElement?.closest('.ehr-source-action')).not.toBeNull());}
 if(mode==='clamped')documentHeight=1300;
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));
 expect(documentTop).toBe(mode==='clamped'?400:693);expect(host.querySelector<HTMLElement>('.mobile-chat-scroll')!.scrollTop).toBe(0);
 expect(composer().value).toBe('Keep my desktop Chief draft and reading position.');expect(document.activeElement).not.toBe(composer());
 expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});

it('does not restore an earlier source document position after leaving and re-entering the bot context',async()=>{
 await openSource();await act(async()=>observed.session!.setSelected('follow_up'));await act(async()=>observed.session!.setSelected('chief'));
 document.documentElement.scrollTop=125;await click('‹ Back to Chief of Staff');await wait(()=>expect(composer()?.disabled).toBe(false));
 expect(documentTop).toBe(125);expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});
