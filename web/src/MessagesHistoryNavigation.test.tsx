import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_MESSAGES_ENABLED','true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
const observed=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null}));
vi.mock('./session/use-workspace-session',async importOriginal=>{const original=await importOriginal<typeof import('./session/use-workspace-session')>();return {...original,useWorkspaceSession:(...args:Parameters<typeof original.useWorkspaceSession>)=>{observed.session=args[0];return original.useWorkspaceSession(...args);}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi} from './workspace-api';
import {workspaceRouteHash,type WorkspaceRoute} from './workspace-route';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const visibleButton=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(button=>!button.closest('[hidden]')&&(button.textContent?.trim()===name||button.getAttribute('aria-label')===name))!;
async function text(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function pop(target:WorkspaceRoute){await act(async()=>{history.replaceState(history.state,'',workspaceRouteHash(target));window.dispatchEvent(new PopStateEvent('popstate'));});}
const target=(bot:string):WorkspaceRoute=>({page:'notebook',workspaceId:observed.session!.getSnapshot().workspace!.id,helper:bot,material:'Conversation'});
beforeEach(async()=>{
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
  window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  await vi.waitFor(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await vi.waitFor(()=>expect(question()?.disabled).toBe(false));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('uses actual popstate to restore each bot draft without replacing the composer',async()=>{
  const composer=question();await text('Keep exact Chief directions on Back.');await pop(target('follow_up'));await vi.waitFor(()=>expect(question().disabled).toBe(false));
  expect(observed.session!.getSnapshot().selected).toBe('follow_up');expect(question().value).toBe('');await text('Keep separate Follow-up directions.');
  await pop(target('chief'));await vi.waitFor(()=>expect(question().value).toBe('Keep exact Chief directions on Back.'));
  await pop(target('follow_up'));await vi.waitFor(()=>expect(question().value).toBe('Keep separate Follow-up directions.'));expect(question()).toBe(composer);
});
it('uses current pending state in the history listener and restores the URL without dispatching or changing bot',async()=>{
  await text('Chief draft behind retained request.');const session=observed.session!,before=location.hash,pending={type:'entry' as const,body:{kind:'scratchpad' as const,content:'Exact retained note',expected_revision:session.getSnapshot().workspace!.revision,idempotency_key:crypto.randomUUID()}};
  const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await act(async()=>session.setPending(pending));await pop(target('follow_up'));
  expect(location.hash).toBe(before);expect(session.getSnapshot().selected).toBe('chief');expect(session.getSnapshot().pending).toBe(pending);expect(question().value).toBe('Chief draft behind retained request.');expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it.each(['conversation','message'] as const)('Back dismisses the %s Details sheet before changing the underlying conversation',async kind=>{
  await text('Retain Chief while dismissing Details.');const before=location.hash;
  await act(async()=>{if(kind==='conversation')visibleButton('Details').click();else host.querySelector<HTMLButtonElement>('.messages-source-details')!.click();});
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();await pop(target('follow_up'));
  expect(host.querySelector('[role="dialog"]')).toBeNull();expect(location.hash).toBe(before);expect(observed.session!.getSnapshot().selected).toBe('chief');expect(question().value).toBe('Retain Chief while dismissing Details.');
  await pop(target('follow_up'));await vi.waitFor(()=>expect(observed.session!.getSnapshot().selected).toBe('follow_up'));expect(question().value).toBe('');
});
