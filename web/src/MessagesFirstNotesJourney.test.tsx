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
import {CHIEF_STARTERS} from './ChiefStartActions';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.setConfig({testTimeout:MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement;
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>visible(item)&&(item.textContent?.trim()===name||item.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
async function click(name:string){await wait(()=>expect(button(name)).toBeTruthy());await wait(()=>expect(button(name)!.disabled).toBe(false));await act(async()=>button(name)!.click());}
async function type(input:HTMLTextAreaElement,value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('takes a new Chief conversation from first notes to an editable task while retaining the unsent message',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),create=vi.spyOn(workspaceApi,'createPrivateDraft');
 await click('New message');const chief=()=>host.querySelector<HTMLButtonElement>('.messages-bot-choices button:nth-child(1)');
 await wait(()=>expect(chief()?.textContent).toContain('Chief of Staff'));await act(async()=>chief()!.click());
 const start=()=>host.querySelector<HTMLButtonElement>('.practice-quick-start button[type="submit"]');await wait(()=>expect(start()?.disabled).toBe(false));await act(async()=>start()!.click());
 await wait(()=>expect(question()?.disabled).toBe(false));await wait(()=>expect(button('Add notes')).toBeTruthy());expect(create).toHaveBeenCalledOnce();
 const composer=question(),workspaceId=create.mock.results[0].value.then((result:Awaited<ReturnType<typeof workspaceApi.createPrivateDraft>>)=>result.workspace.id);
 await type(composer,'Keep these invented Chief directions unsent.');await click('Add notes');
 await wait(()=>expect(host.querySelector('.messages-thread-header h1')?.textContent).toBe('Notes'));const notebook=host.querySelector<HTMLTextAreaElement>('#team-notebook')!;
 expect(visible(notebook)).toBe(true);expect(composer.value).toBe('Keep these invented Chief directions unsent.');expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 await type(notebook,'Invented follow-up note: clarify sleep diary timing and missing medication history.');await click('Save notebook revision');await wait(()=>expect(append).toHaveBeenCalledOnce());
 expect(append.mock.calls[0][1]).toBe(await workspaceId);expect(append.mock.calls[0][2]).toMatchObject({kind:'scratchpad',content:'Invented follow-up note: clarify sleep diary timing and missing medication history.'});
 await click('‹ Back to Chief of Staff');await wait(()=>expect(question().disabled).toBe(false));expect(question()).toBe(composer);expect(composer.value).toBe('Keep these invented Chief directions unsent.');expect(button('Add notes')).toBeUndefined();expect(ask).not.toHaveBeenCalled();
 await type(composer,'');await click('Organize saved notes');expect(composer.value).toBe(CHIEF_STARTERS[0].prompt);expect(ask).not.toHaveBeenCalled();expect(append).toHaveBeenCalledOnce();expect(create).toHaveBeenCalledOnce();
});
