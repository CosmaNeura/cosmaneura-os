import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {waitMessagesJourney as wait,MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.setConfig({testTimeout:MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement;
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>visible(item)&&(item.textContent?.trim()===name||item.getAttribute('aria-label')===name));
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>button(name)!.click());}
async function type(input:HTMLTextAreaElement,value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('innerWidth',320);vi.stubGlobal('innerHeight',640);
 localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('reads, saves and confirms a mobile note before intentionally preparing Chief drafts, retaining the original unsent conversation',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),save=vi.spyOn(workspaceApi,'saveNote'),review=vi.spyOn(workspaceApi,'reviewNote');
 const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(item=>item.textContent?.includes('Chief of Staff'));
 await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());
 const composer=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
 await wait(()=>expect(composer()?.disabled).toBe(false));const original=composer();await type(original,'Keep this invented question unsent while I review the note.');
 await click('Details');await click('Visit note');
 const section=()=>host.querySelector<HTMLElement>('.team-note-review[data-compact=true]')!;
 await wait(()=>expect(section()).toBeTruthy());const text=section().querySelector<HTMLTextAreaElement>('#private-note-text')!;
 expect(visible(text)).toBe(true);expect(text.compareDocumentPosition(button('Save note')!)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 await type(text,'Invented note: confirm sleep diary timing and obtain the missing medication history.');await click('Save note');
 await wait(()=>expect(save).toHaveBeenCalledOnce());await wait(()=>expect(button('Confirm review')?.disabled).toBe(true));
 expect(review).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();expect(original.value).toBe('Keep this invented question unsent while I review the note.');
 const acknowledgement=()=>section().querySelector<HTMLInputElement>('.team-note-approval input[type="checkbox"]')!;
 expect(text.compareDocumentPosition(acknowledgement())&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 await act(async()=>acknowledgement().click());await click('Confirm review');await wait(()=>expect(review).toHaveBeenCalledOnce());
 const saved=(await save.mock.results[0].value).workspace.note!.latest!;
 expect(review.mock.calls[0][2]).toBe(saved.id);expect(review.mock.calls[0][3]).toMatchObject({content_hash:saved.content_hash,source_fingerprint:saved.source_fingerprint});
 await wait(()=>expect(section().textContent).toContain('Reviewed privately'));await click('‹ Back to Chief of Staff');
 await wait(()=>expect(composer().disabled).toBe(false));expect(composer()).toBe(original);expect(original.value).toBe('Keep this invented question unsent while I review the note.');expect(ask).not.toHaveBeenCalled();
 await type(original,'');await click('Details');await click('Visit note');await click('Prepare with Chief');
 await wait(()=>expect(ask).toHaveBeenCalledOnce());expect(JSON.parse(ask.mock.calls[0][2].content)).toMatchObject({contract:'clinical-team-drafts.request.v1',note_id:saved.id,note_version:saved.version,content_hash:saved.content_hash});
 expect(save).toHaveBeenCalledOnce();expect(review).toHaveBeenCalledOnce();
});
