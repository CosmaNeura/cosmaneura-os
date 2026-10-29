import {act,StrictMode} from 'react';
import {waitMessagesJourney as wait} from './messages-journey-wait';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const name of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(name,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
const observed=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null,guards:[] as (()=>boolean)[]}));
vi.mock('./session/use-workspace-session',async original=>{const module=await original<typeof import('./session/use-workspace-session')>();return {...module,useWorkspaceSession:(...args:Parameters<typeof module.useWorkspaceSession>)=>{observed.session=args[0];return module.useWorkspaceSession(...args);}};});
vi.mock('./WorkspaceDialog',async original=>{const module=await original<typeof import('./WorkspaceDialog')>();return {...module,WorkspaceDialog:(props:Parameters<typeof module.WorkspaceDialog>[0])=>{if(props.canRestoreFocus)observed.guards.push(props.canRestoreFocus);return <module.WorkspaceDialog {...props}/>;}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement,owner:AuthenticatedWorkspaceIdentity,nativeCurrent:boolean;
const composer=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(e=>!e.closest('[hidden]')&&(e.textContent?.trim()===name||e.getAttribute('aria-label')===name))!;

async function click(name:string){await wait(()=>expect(button(name)).toBeTruthy());await wait(()=>expect(button(name)!.disabled).toBe(false));await act(async()=>button(name).click());}
async function draft(){await act(async()=>{const input=composer();input.focus();Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'Keep my native Chief draft and reading position.');input.dispatchEvent(new Event('input',{bubbles:true}));});}
function reader(){const scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll,'clientHeight',{configurable:true,value:149});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:3593});scroll.scrollTop=3423;return scroll;}
async function mount(strict=false){const content=<EncounterWorkspace authenticated={owner} draftStorage={memoryDraftStorage()}/>;await act(async()=>root.render(strict?<StrictMode>{content}</StrictMode>:content));await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')).toBeTruthy());await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')!.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await wait(()=>expect(composer()).toBeTruthy());await wait(()=>expect(composer()!.disabled).toBe(false));}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);nativeCurrent=true;observed.guards=[];owner={...identity,nativeSession:{revision:'00000000-0000-4000-8000-000000000995',isCurrent:()=>nativeCurrent}};await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it.each([['conversation','close'],['message','close'],['conversation','escape'],['message','escape'],['conversation','back']] as const)('closes native %s details by %s to its invoking button when tap activation leaves the composer focused',async(kind,dismiss)=>{
 await draft();const scroll=reader(),input=composer(),focus=vi.spyOn(input,'focus'),opener=kind==='conversation'?button('Details'):host.querySelector<HTMLButtonElement>('.messages-source-details')!;
 await act(async()=>opener.click());expect(host.querySelector('[role="dialog"]')).not.toBeNull();if(dismiss==='escape')await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));else await click(dismiss==='back'?'Back to Chief of Staff':kind==='conversation'?'Close conversation details':'Close message details');
 expect(document.activeElement).toBe(opener);expect(focus).not.toHaveBeenCalled();await wait(()=>expect(scroll.scrollTop).toBe(3423));expect(input.value).toBe('Keep my native Chief draft and reading position.');
});

it('opens a cited source from Message details and returns to the surviving invoking control',async()=>{
 const session=observed.session!,workspace=session.getSnapshot().workspace!,source=workspace.entries.find(entry=>entry.kind==='synthetic_source')!;
 await act(async()=>session.setWorkspace({...workspace,entries:workspace.entries.map(entry=>entry.reply?.role==='chief'?{...entry,reply:{...entry.reply,citations:[{entry_id:source.id,revision:source.revision,label:'Invented saved input',kind:source.kind}]}}:entry)}));
 await draft();const scroll=reader(),input=composer(),focus=vi.spyOn(input,'focus'),opener=host.querySelector<HTMLButtonElement>('.messages-source-details')!,ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');
 await act(async()=>opener.click());await click('Invented saved input');await wait(()=>expect(document.activeElement?.id).toBe('source-'+source.id));expect(focus).not.toHaveBeenCalled();expect(host.querySelector('[role="dialog"]')).toBeNull();
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(opener));await wait(()=>expect(scroll.scrollTop).toBe(3423));expect(input.value).toBe('Keep my native Chief draft and reading position.');expect(focus).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});

it('does not refocus an obsolete dialog opener after Chief changes context and returns on the same nodes',async()=>{
 await draft();const opener=button('Details');await act(async()=>opener.click());const focus=vi.spyOn(opener,'focus'),session=observed.session!;
 await act(async()=>session.setSelected('follow_up'));await act(async()=>session.setSelected('chief'));expect(button('Details')).toBe(opener);await click('Close conversation details');expect(focus).not.toHaveBeenCalled();
});

it('keeps task focus when Details opens Saved sources and preserves the existing compose-return action',async()=>{
 await draft();const input=composer(),focus=vi.spyOn(input,'focus');await click('Details');await click('Choose notes or sources');await click('Saved sources');await wait(()=>expect(document.activeElement).toBe(host.querySelector('.messages-thread-header h1')));expect(document.activeElement?.textContent).toBe('Saved sources');expect(focus).not.toHaveBeenCalled();expect(input.value).toBe('Keep my native Chief draft and reading position.');
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(input));expect(input.value).toBe('Keep my native Chief draft and reading position.');
});

it('returns through source choices and Details to the unchanged native chat draft and reading position',async()=>{
 await draft();const scroll=reader(),input=composer(),focus=vi.spyOn(input,'focus'),opener=button('Details');await click('Details');const dialog=host.querySelector<HTMLElement>('[role="dialog"]')!;dialog.scrollTop=161;
 await click('Choose notes or sources');expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);expect(host.querySelector('[role="dialog"]')).toBe(dialog);expect(document.activeElement).toBe(button('Back to details'));
 await click('Back to details');expect(document.activeElement).toBe(button('Choose notes or sources'));expect(dialog.scrollTop).toBe(161);await click('Back to Chief of Staff');
 expect(document.activeElement).toBe(opener);expect(focus).not.toHaveBeenCalled();await wait(()=>expect(scroll.scrollTop).toBe(3423));expect(input.value).toBe('Keep my native Chief draft and reading position.');
});

it.each(['conversation','message'] as const)('expires the actual %s dialog guard when the workspace unmounts',async kind=>{
 await draft();await act(async()=>{if(kind==='conversation')button('Details').click();else host.querySelector<HTMLButtonElement>('.messages-source-details')!.click();});const guard=observed.guards.at(-1)!;expect(guard()).toBe(true);await act(async()=>root.unmount());root=createRoot(host);expect(guard()).toBe(false);
});

it.each(['session','foreground'] as const)('does not restore a native opener after losing %s ownership',async kind=>{
 await draft();await click('Details');const opener=button('Details'),focus=vi.spyOn(opener,'focus');if(kind==='session')nativeCurrent=false;else await act(async()=>notifyNativeWorkspaceForeground(owner,false));await click('Close conversation details');expect(focus).not.toHaveBeenCalled();if(kind==='foreground')await act(async()=>notifyNativeWorkspaceForeground(owner,true));
});

it.each(['conversation','message'] as const)('restores the current %s Details opener after StrictMode teardown and setup replay',async kind=>{
 await act(async()=>root.unmount());root=createRoot(host);history.replaceState(null,'','#cosmas/home');await mount(true);await draft();const opener=kind==='conversation'?button('Details'):host.querySelector<HTMLButtonElement>('.messages-source-details')!;await act(async()=>opener.click());await click(kind==='conversation'?'Close conversation details':'Close message details');expect(document.activeElement).toBe(opener);
});
