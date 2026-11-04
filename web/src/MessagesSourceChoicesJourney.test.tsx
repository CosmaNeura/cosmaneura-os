import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {waitMessagesJourney as wait,MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
const observed=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null}));
vi.mock('./session/use-workspace-session',async original=>{const value=await original<typeof import('./session/use-workspace-session')>();return {...value,useWorkspaceSession:(...args:Parameters<typeof value.useWorkspaceSession>)=>{observed.session=args[0];return value.useWorkspaceSession(...args);}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
import {teamSetupApi} from './team-setup-api';
import {configurationHash} from './team-setup-request';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.setConfig({testTimeout:MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement;
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>visible(item)&&(item.textContent?.trim()===name||item.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>button(name)!.click());}
async function type(input:HTMLTextAreaElement,value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 const team=await workspaceApi.team(identity),setup=await teamSetupApi.read(identity);team.configuration.bots=team.configuration.bots.map(bot=>bot.role==='chief'?{...bot,include_notebook:false,include_evidence:false}:bot);
 const createPrivateDraft=workspaceApi.createPrivateDraft;vi.spyOn(workspaceApi,'createPrivateDraft').mockImplementation(async(...args)=>({...await createPrivateDraft(...args),team}));
 vi.spyOn(workspaceApi,'team').mockResolvedValue(team);vi.spyOn(teamSetupApi,'read').mockResolvedValue({...setup,team,setup:{...setup.setup,configuration_sha256:await configurationHash(team.configuration)}});
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await click('New message');const chief=()=>host.querySelector<HTMLButtonElement>('.messages-bot-choices button:nth-child(1)');await wait(()=>expect(chief()?.textContent).toContain('Chief of Staff'));await act(async()=>chief()!.click());const start=()=>host.querySelector<HTMLButtonElement>('.practice-quick-start button[type=\"submit\"]');await wait(()=>expect(start()?.disabled).toBe(false));await act(async()=>start()!.click());await wait(()=>expect(question()?.disabled).toBe(false));expect(observed.session!.getSnapshot().team!.configuration.bots.find(bot=>bot.role==='chief')).toMatchObject({include_notebook:false,include_evidence:false});
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('opens current Chief source choices explicitly and returns with the same unsent question and unchanged permissions',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),save=vi.spyOn(workspaceApi,'saveTeam'),append=vi.spyOn(workspaceApi,'append');const composer=question(),draft='Keep this invented Chief question while I review access.';
 await type(composer,draft);await click('Review source choices');await wait(()=>expect(host.querySelector('.team-configuration-flow')?.getAttribute('data-page')).toBe('advanced'));
 const choices=()=>[...host.querySelectorAll<HTMLDetailsElement>('.team-optional-settings')].find(item=>item.querySelector('summary')?.textContent==='Sources this bot can use')!;
 expect(choices().open).toBe(true);expect(choices().closest('[hidden]')).toBeNull();expect([...choices().querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].map(item=>item.checked)).toEqual([false,false]);
 expect(observed.session!.getSnapshot().selected).toBe('chief');expect(composer.value).toBe(draft);expect(ask).not.toHaveBeenCalled();expect(save).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 await click('Done');await wait(()=>expect(question().disabled).toBe(false));expect(question()).toBe(composer);expect(composer.value).toBe(draft);expect(button('Review source choices')?.disabled).toBe(false);expect(observed.session!.getSnapshot().team!.configuration.bots.find(bot=>bot.role==='chief')).toMatchObject({include_notebook:false,include_evidence:false});expect(ask).not.toHaveBeenCalled();expect(save).not.toHaveBeenCalled();
});
it('blocks source-choice navigation while notebook changes are unsaved and preserves both drafts',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),save=vi.spyOn(workspaceApi,'saveTeam'),append=vi.spyOn(workspaceApi,'append');const composer=question();await type(composer,'Unsent invented Chief directions.');
 await click('Add notes or sources');await click('Notebook');const notebook=host.querySelector<HTMLTextAreaElement>('#team-notebook')!,original=notebook.value;await type(notebook,original+' Invented unsaved notebook change.');
 await click('‹ Back to Chief of Staff');await wait(()=>expect(button('Review source choices')?.disabled).toBe(true));await act(async()=>button('Review source choices')!.click());expect(observed.session!.getSnapshot().settingsOpen).toBe(false);expect(composer.value).toBe('Unsent invented Chief directions.');expect(notebook.value).toBe(original+' Invented unsaved notebook change.');expect(ask).not.toHaveBeenCalled();expect(save).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('does not open source settings during an existing pending operation or reuse a source action for another bot',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),save=vi.spyOn(workspaceApi,'saveTeam'),composer=question();await type(composer,'Keep this invented pending-work draft.');
 const pending={type:'entry' as const,body:{kind:'scratchpad' as const,content:'An existing invented write',expected_revision:observed.session!.getSnapshot().workspace!.revision,idempotency_key:'20000000-0000-4000-8000-000000000001'}};
 await act(async()=>observed.session!.setPending(pending));expect(button('Review source choices')?.disabled).toBe(true);await act(async()=>button('Review source choices')!.click());expect(observed.session!.getSnapshot().settingsOpen).toBe(false);expect(observed.session!.getSnapshot().pending).toBe(pending);expect(composer.value).toBe('Keep this invented pending-work draft.');
 await act(async()=>observed.session!.setPending(null));const old=button('Review source choices')!;await act(async()=>observed.session!.setSelected('follow_up'));await act(async()=>old.click());expect(observed.session!.getSnapshot().settingsOpen).toBe(false);expect(ask).not.toHaveBeenCalled();expect(save).not.toHaveBeenCalled();
});
