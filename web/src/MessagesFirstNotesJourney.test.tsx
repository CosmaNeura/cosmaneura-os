import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {waitMessagesJourney as wait,MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_FEATURE_PROFILE','independent-beta-v1');});
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
it('takes an independent beta user directly from New message to first notes and an editable Chief task while retaining the unsent message',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),create=vi.spyOn(workspaceApi,'createPrivateDraft');
 await click('New message');expect(host.querySelector('.messages-bot-choices')).toBeNull();expect(create).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();
 const start=()=>host.querySelector<HTMLButtonElement>('.practice-quick-start button[type="submit"]');await wait(()=>expect(start()?.disabled).toBe(false));await act(async()=>start()!.click());
 await wait(()=>expect(question()?.disabled).toBe(false));await wait(()=>expect(button('Add notes')).toBeTruthy());expect(create).toHaveBeenCalledOnce();
 const composer=question(),workspaceId=create.mock.results[0].value.then((result:Awaited<ReturnType<typeof workspaceApi.createPrivateDraft>>)=>result.workspace.id);
 await type(composer,'Keep these invented Chief directions unsent.');await click('Add notes');
 await wait(()=>expect(host.querySelector('.messages-thread-header h1')?.textContent).toBe('Notes'));const notebook=host.querySelector<HTMLTextAreaElement>('#team-notebook')!;
 expect(visible(notebook)).toBe(true);expect(composer.value).toBe('Keep these invented Chief directions unsent.');expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 await type(notebook,'Invented follow-up note: clarify sleep diary timing and missing medication history.');await click('Save notebook revision');await wait(()=>expect(append).toHaveBeenCalledOnce());
 expect(append.mock.calls[0][1]).toBe(await workspaceId);expect(append.mock.calls[0][2]).toMatchObject({kind:'scratchpad',content:'Invented follow-up note: clarify sleep diary timing and missing medication history.'});
 await click('‹ Back to Chief of Staff');await wait(()=>expect(question().disabled).toBe(false));expect(question()).toBe(composer);expect(composer.value).toBe('Keep these invented Chief directions unsent.');expect(button('Add notes')).toBeUndefined();expect(ask).not.toHaveBeenCalled();
 await click('Details');await click('Prepare a Chief task');await wait(()=>expect(host.querySelector('.messages-thread-header h1')?.textContent).toBe('Tools'));
 const tasks=()=>host.querySelector<HTMLDetailsElement>('.chief-starters-disclosure')!;await act(async()=>tasks().querySelector('summary')!.click());expect(tasks().open).toBe(true);
 for(const starter of CHIEF_STARTERS){expect(button(starter.label)?.disabled).toBe(true);await act(async()=>button(starter.label)!.click());}
 expect(composer.value).toBe('Keep these invented Chief directions unsent.');expect(ask).not.toHaveBeenCalled();
 await click('‹ Back to Chief of Staff');await type(composer,'');await click('Details');await click('Prepare a Chief task');
 if(!tasks().open)await act(async()=>tasks().querySelector('summary')!.click());await click('Plan follow-up and research');
 await wait(()=>expect(question().disabled).toBe(false));expect(question()).toBe(composer);expect(composer.value).toBe(CHIEF_STARTERS[3].prompt);expect(composer.closest('[hidden]')).toBeNull();expect(ask).not.toHaveBeenCalled();expect(append).toHaveBeenCalledOnce();
 await type(composer,'');await click('Organize saved notes');expect(composer.value).toBe(CHIEF_STARTERS[0].prompt);expect(ask).not.toHaveBeenCalled();expect(append).toHaveBeenCalledOnce();expect(create).toHaveBeenCalledOnce();
 for(const label of ['Draft a visit note','Draft patient instructions']){
  await type(composer,'');await click('Details');await click('Prepare a Chief task');
  if(!tasks().open)await act(async()=>tasks().querySelector('summary')!.click());await click(label);
  await wait(()=>expect(question().disabled).toBe(false));expect(question()).toBe(composer);expect(composer.closest('[hidden]')).toBeNull();
  expect(composer.value).toContain(label==='Draft a visit note'?'Subjective, Objective, Assessment and Plan':'plain-language patient instructions');
  expect(composer.value).toContain('My directions: ');await type(composer,composer.value+'Use the invented sleep-diary note; keep medication details missing.');
  expect(composer.value).toContain('keep medication details missing.');expect(ask).not.toHaveBeenCalled();expect(append).toHaveBeenCalledOnce();expect(create).toHaveBeenCalledOnce();
 }
});
