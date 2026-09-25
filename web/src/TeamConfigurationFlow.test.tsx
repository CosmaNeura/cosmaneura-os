import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {TeamConfigurationFlow} from './TeamConfigurationFlow';
import {modelActivityApi} from './model-activity-api';
import {activityContext,activityPage} from './model-activity-test-fixture';
import {teamSetupApi} from './team-setup-api';
import {teamFixture,catalogFixture,projectionFixture,rehearsalFixture} from './team-setup-test-fixture';
import {setupChange,type SetupProjection} from './team-setup-request';
import {type ReviewedTeamDraft} from './TeamSetupPanel';
import {botAddress,type ProviderTeam,type TeamConfiguration} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./model-activity-api',()=>({modelActivityApi:{read:vi.fn()}}));
vi.mock('./team-setup-api',()=>({teamSetupApi:{read:vi.fn(),rehearse:vi.fn(),resources:vi.fn(),usage:vi.fn()}}));
const activityOpen=vi.fn();
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
let element:HTMLDivElement,root:Root,latest:TeamConfiguration,review:ReviewedTeamDraft|null,saved:{draft:TeamConfiguration;review:ReviewedTeamDraft|null}|null,refresh:ReturnType<typeof vi.fn>;
function visible(node:Element):boolean{
  if(node.closest('[hidden]'))return false;
  let parent=node.parentElement;while(parent){if(parent.tagName==='DETAILS'&&!(parent as HTMLDetailsElement).open&&!parent.querySelector('summary')?.contains(node))return false;parent=parent.parentElement;}return true;
}
const buttons=()=>[...element.querySelectorAll('button')].filter(visible);
const buttonName=(node:Element)=>{const copy=node.cloneNode(true) as Element;copy.querySelectorAll('[aria-hidden=true]').forEach(child=>child.remove());return copy.textContent?.trim();};
const button=(text:string)=>{const found=buttons().find(node=>buttonName(node)===text);expect(found,text).toBeTruthy();return found!;};
const input=(label:string)=>{const found=[...element.querySelectorAll('label')].filter(visible).find(node=>node.textContent?.trim().startsWith(label))?.querySelector('input,textarea,select');expect(found,label).toBeTruthy();return found as HTMLInputElement;};
const wait=async(check:()=>void)=>{await vi.waitFor(async()=>{await act(async()=>{});check();});};
const click=async(text:string)=>{const node=button(text);expect(node.disabled,text).toBe(false);await act(async()=>node.click());};
const fill=async(label:string,value:string)=>{const node=input(label),kind=node.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:node.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;await act(async()=>{Object.getOwnPropertyDescriptor(kind,'value')!.set!.call(node,value);node.dispatchEvent(new Event(node.tagName==='SELECT'?'change':'input',{bubbles:true}));});};
async function chooseBot(name:string){const node=buttons().find(button=>button.closest('.team-coworker-overview')&&button.querySelector('strong')?.textContent===name);expect(node,name).toBeTruthy();await act(async()=>node!.click());}
function Harness({initialTeam=teamFixture(),initialDraft=initialTeam.configuration,locked=false,activity=false}:{initialTeam?:ProviderTeam;initialDraft?:TeamConfiguration;locked?:boolean;activity?:boolean}){
  const [team,setTeam]=useState(initialTeam),[draft,setDraft]=useState(structuredClone(initialDraft)),[selected,setSelected]=useState('scribe'),[approval,setApproval]=useState<ReviewedTeamDraft|null>(null),[setup,setSetup]=useState<SetupProjection|null>(null);
  latest=draft;review=approval;
  return <TeamConfigurationFlow activity={activity?{context:activityContext,onOpenEncounter:activityOpen}:undefined} identity={identity} team={team} draft={draft} setDraft={setDraft} selected={selected} setSelected={setSelected} locked={locked}
    setupAvailable={setup?.team_revision===team.revision} reviewRequired={setupChange(team.configuration,draft)&&!(approval?.revision===team.revision&&approval.configurationKey===JSON.stringify(draft))}
    onCurrentTeam={(value,projection)=>{setTeam(value);setSetup(projection);}} onReviewChange={setApproval} onAccessLost={()=>{}}
    onSave={()=>{saved={draft:structuredClone(draft),review:approval};}} onClose={()=>{}} onRefresh={()=>{refresh();setApproval(null);}}/>;
}
async function mount(props:Parameters<typeof Harness>[0]={}){await act(async()=>root.render(<Harness {...props}/>));await wait(()=>expect(teamSetupApi.read).toHaveBeenCalled());}
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();saved=null;review=null;refresh=vi.fn();element=document.createElement('div');document.body.append(element);root=createRoot(element);
  vi.mocked(modelActivityApi.read).mockResolvedValue(activityPage());const team=teamFixture();vi.mocked(teamSetupApi.read).mockResolvedValue({team,catalog:catalogFixture(),setup:await projectionFixture(team.configuration)});vi.mocked(teamSetupApi.rehearse).mockImplementation(async(_,body)=>rehearsalFixture(body.configuration,body.expected_revision));});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();});

it('starts with a compact coworker overview and no configuration inputs or duplicate exit',async()=>{await mount();expect([...element.querySelectorAll('input,select,textarea')].filter(visible)).toHaveLength(0);expect(buttons()).toHaveLength(8);expect(buttons().some(b=>b.textContent==='Done')).toBe(false);expect(teamSetupApi.rehearse).not.toHaveBeenCalled();await click('Review changes');expect(button('Save team changes').disabled).toBe(true);expect(element.textContent).toContain('No settings have changed');});
it('edits only one coworker with three essential fields and preserves all default and restricted settings',async()=>{const draft=teamFixture().configuration;draft.bots[0].resources={version:1,allowed:[]};await mount({initialDraft:draft});await chooseBot('Scribe');expect([...element.querySelectorAll('input,select,textarea')].filter(visible)).toHaveLength(3);await fill('Bot name','My Scribe');await fill('Working preferences','Keep my phrasing');await click('Done editing');await chooseBot('visit prep');expect(input('Bot name').value).toBe('visit prep');expect(latest.bots[0]).toMatchObject({name:'My Scribe',response_style:'brief',include_notebook:true,include_evidence:true,resources:{version:1,allowed:[]},working_preferences:'Keep my phrasing'});expect(latest.bots.slice(1)).toEqual(draft.bots.slice(1));expect(teamSetupApi.read).toHaveBeenCalledTimes(1);});
it('edits practice context once outside the bot editor and saves the exact parent draft',async()=>{await mount();await click('Team preferences');await click('Practice context');expect([...element.querySelectorAll('textarea,input,select')].filter(visible)).toHaveLength(1);await fill('Practice context','Invented private practice preferences');await click('Done editing');await click('Review changes');expect(element.textContent).toContain('Invented private practice preferences');await click('Save team changes');expect(saved?.draft.practice_context).toBe('Invented private practice preferences');expect(teamSetupApi.rehearse).not.toHaveBeenCalled();});
it('creates multiple custom coworkers without replacing existing identities or granting additional skills',async()=>{await mount();const original=structuredClone(latest.bots);await click('Add a coworker');await click('Create custom bot');await fill('Bot name','Referral helper');await fill('Job (required)','Prepare a referral checklist');await click('Done editing');await click('Add a coworker');await click('Create custom bot');await fill('Bot name','Follow-up helper');await fill('Job (required)','Review unfinished tasks');await click('Done editing');expect(latest.bots.slice(0,4)).toEqual(original);expect(new Set(latest.bots.slice(4).map(botAddress)).size).toBe(2);expect(latest.bots.slice(4).map(bot=>bot.skills)).toEqual([['saved_context','work_status'],['saved_context','work_status']]);await click('Review changes');await click('Save team changes');expect(saved?.draft.bots).toEqual(latest.bots);});
it('does not save a custom coworker without its required job',async()=>{await mount();await click('Add a coworker');await click('Create custom bot');await click('Done editing');await click('Review changes');expect(button('Save team changes').disabled).toBe(true);expect(element.textContent).toContain('Finish each coworker');expect(saved).toBeNull();});
async function addGroup(){await click('Add a team group');const front=buttons().find(b=>b.querySelector('strong')?.textContent==='Front desk')!;await act(async()=>front.click());await click('Add Front desk to draft');}
async function approveGroup(){await click('Review changes');expect(button('Save team changes').disabled).toBe(true);await wait(()=>expect(input('I reviewed these team changes')).toBeTruthy());await wait(()=>expect(input('I reviewed these team changes').checked).toBe(false));expect(button('Save team changes').disabled).toBe(true);await act(async()=>input('I reviewed these team changes').click());await wait(()=>expect(button('Save team changes').disabled).toBe(false));}
it('keeps the exact rehearsal mounted across page navigation without restoring or automatically ticking consent',async()=>{await mount();await addGroup();const ids=latest.bots.map(botAddress);await approveGroup();const proof=structuredClone(review);await click('← Back');await click('Team preferences');await click('← Back');await click('Review changes');expect(review).toEqual(proof);expect(input('I reviewed these team changes').checked).toBe(true);expect(teamSetupApi.read).toHaveBeenCalledTimes(1);expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(1);await click('Save team changes');expect(saved?.draft.bots.map(botAddress)).toEqual(ids);expect(saved?.review).toEqual(proof);});
it('invalidates the exact review after an essential edit and automatically rechecks before a new explicit confirmation',async()=>{await mount();await addGroup();await approveGroup();await click('← Back');await chooseBot('Scribe');await fill('Bot name','Changed after review');await click('Done editing');await click('Review changes');expect(review).toBeNull();expect(button('Save team changes').disabled).toBe(true);await wait(()=>expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(2));expect(input('I reviewed these team changes').checked).toBe(false);expect(latest.bots[0].name).toBe('Changed after review');});
it('refreshes current prerequisites without resetting the draft or retaining consent',async()=>{await mount();await addGroup();await approveGroup();const draft=structuredClone(latest);await click('← Back');await click('Team preferences');await click('Refresh current settings');await wait(()=>expect(teamSetupApi.read).toHaveBeenCalledTimes(2));expect(refresh).toHaveBeenCalledTimes(1);expect(latest).toEqual(draft);await click('← Back');await click('Review changes');expect(review).toBeNull();expect(button('Save team changes').disabled).toBe(true);});
it('retains reversible retirement across review and undo without changing source permissions',async()=>{const draft=teamFixture().configuration;draft.bots.push({role:'custom',instance_id:crypto.randomUUID(),name:'Paused custom',enabled:false,response_style:'brief',include_notebook:false,include_evidence:false,job_focus:'Review owned work',skills:['work_status'],resources:{version:1,allowed:[]}});const team=teamFixture(draft);vi.mocked(teamSetupApi.read).mockResolvedValue({team,catalog:catalogFixture(),setup:await projectionFixture(draft)});await mount({initialTeam:team});await chooseBot('Paused custom');await click('Skills, permissions and source access →');await click('Retire bot when saved');await click('Done editing');await click('Done editing');await click('Review changes');await click('← Back');const summary=element.querySelector('details>summary')!;await act(async()=>summary.dispatchEvent(new MouseEvent('click',{bubbles:true})));(summary.parentElement as HTMLDetailsElement).open=true;await click('Paused custom · Retired');await click('Skills, permissions and source access →');await click('Undo retirement');expect(latest.bots.at(-1)).toEqual(draft.bots.at(-1));expect(latest.bots.at(-1)?.enabled).toBe(false);expect(latest.bots.at(-1)?.resources).toEqual({version:1,allowed:[]});});
it('shows policy controls only on their focused pages and keeps inherited defaults unchanged',async()=>{const {policySetupFixture,resourcesFixture,usageFixture}=await import('./team-policy-test-fixture');vi.mocked(teamSetupApi.read).mockResolvedValue(await policySetupFixture());vi.mocked(teamSetupApi.resources).mockResolvedValue(resourcesFixture);vi.mocked(teamSetupApi.usage).mockResolvedValue(usageFixture);await mount();const original=structuredClone(latest);await click('Team preferences');await click('AI work limit');expect([...element.querySelectorAll('input,select,textarea')].filter(visible)).toHaveLength(0);await click('Add attempt limit to draft');expect([...element.querySelectorAll('input,select,textarea')].filter(visible)).toHaveLength(1);expect(latest.model_work?.max_attempts_per_24h).toBe(0);await click('Done editing');await click('← Back');await chooseBot('Scribe');await click('Skills, permissions and source access →');await click('Choose preparation and scheduling sources →');expect(element.querySelectorAll('[data-source-editor]')).toHaveLength(1);expect(element.querySelector('[data-source-editor]')?.getAttribute('data-source-editor')).toBe('scribe');expect(latest.bots).toEqual(original.bots);});
it('restores the parent draft without restoring any previous review confirmation',async()=>{await mount();await addGroup();await approveGroup();const draft=structuredClone(latest);await act(async()=>root.unmount());root=createRoot(element);await mount({initialDraft:draft});await click('Review changes');expect(review).toBeNull();expect(button('Save team changes').disabled).toBe(true);expect(latest).toEqual(draft);expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(2);});
it('keeps editing and save disabled while the parent exact recovery operation is locked',async()=>{await mount({locked:true});expect(button('Add a coworker').disabled).toBe(true);expect(button('Review changes').disabled).toBe(true);await chooseBot('Scribe');expect([...element.querySelectorAll('input,textarea')].filter(visible).every(node=>(node as HTMLInputElement).disabled)).toBe(true);expect(button('Done editing').disabled).toBe(true);expect(saved).toBeNull();});


it('keeps activity optional and performs no hidden read before explicitly opening it',async()=>{await mount();await click('Team preferences');expect(buttons().some(b=>buttonName(b)==='AI activity')).toBe(false);expect(modelActivityApi.read).not.toHaveBeenCalled();await act(async()=>root.unmount());root=createRoot(element);await mount({activity:true});expect(modelActivityApi.read).not.toHaveBeenCalled();await click('Team preferences');await click('AI activity');expect(modelActivityApi.read).toHaveBeenCalledOnce();expect(buttons().some(b=>buttonName(b)==='Save team changes')).toBe(false);});
it('retains the exact team draft and reviewed rehearsal through activity and return without saving',async()=>{await mount({activity:true});await addGroup();await approveGroup();const draft=structuredClone(latest),proof=structuredClone(review);await click('← Back');await click('Team preferences');await click('AI activity');await click('← Back');await click('← Back');await click('Review changes');expect(latest).toEqual(draft);expect(review).toEqual(proof);expect(input('I reviewed these team changes').checked).toBe(true);expect(saved).toBeNull();expect(teamSetupApi.rehearse).toHaveBeenCalledOnce();expect(teamSetupApi.read).toHaveBeenCalledOnce();});
it('blocks entering activity while the parent exact request is locked',async()=>{await mount({activity:true,locked:true});await click('Team preferences');expect(button('AI activity').disabled).toBe(true);await act(async()=>button('AI activity').click());expect(modelActivityApi.read).not.toHaveBeenCalled();expect(element.querySelector('[data-page]')?.getAttribute('data-page')).toBe('preferences');});
it('keeps Back locked while current activity or encounter authorization is pending',async()=>{let release!:(value:ReturnType<typeof activityPage>)=>void;vi.mocked(modelActivityApi.read).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));await mount({activity:true});await click('Team preferences');await click('AI activity');expect(button('← Back').disabled).toBe(true);await act(async()=>button('← Back').click());expect(element.querySelector('[data-page]')?.getAttribute('data-page')).toBe('activity');await act(async()=>release(activityPage()));expect(button('← Back').disabled).toBe(false);expect(saved).toBeNull();});

it('automatically checks once, retains a failure without looping, and retries only when requested',async()=>{
  vi.mocked(teamSetupApi.rehearse).mockRejectedValueOnce(new Error('temporary setup failure'));
  await mount();await addGroup();const original=structuredClone(latest);await click('Review changes');
  await wait(()=>expect(element.textContent).toContain('Team settings could not be checked'));
  expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(1);expect(latest).toEqual(original);
  expect(review).toBeNull();expect(button('Save team changes').disabled).toBe(true);
  await click('← Back');await click('Review changes');expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(1);
  await click('Check team settings');await wait(()=>expect(input('I reviewed these team changes').checked).toBe(false));
  expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(2);expect(saved).toBeNull();expect(review).toBeNull();
});

it('discards a pending automatic result after an edit and checks the new exact draft without saving',async()=>{
  let release!:(value:Awaited<ReturnType<typeof rehearsalFixture>>)=>void;
  vi.mocked(teamSetupApi.rehearse).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  await mount();await addGroup();await click('Review changes');
  expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(1);const old=structuredClone(latest);
  await click('← Back');await chooseBot('chief');await fill('Bot name','Practice coordinator');
  await click('Done editing');await click('Review changes');const edited=structuredClone(latest);
  await act(async()=>release(await rehearsalFixture(old)));
  await wait(()=>expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(2));
  expect(latest.bots.find(bot=>bot.role==='chief')?.name).toBe('Practice coordinator');
  expect(vi.mocked(teamSetupApi.rehearse).mock.calls[1][1].configuration).toEqual(edited);
  expect(input('I reviewed these team changes').checked).toBe(false);expect(review).toBeNull();expect(saved).toBeNull();
});

it('rechecks after a temporary lock discards an automatic result and still requires review and save',async()=>{
  let release!:(value:Awaited<ReturnType<typeof rehearsalFixture>>)=>void;
  vi.mocked(teamSetupApi.rehearse).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  await mount();await addGroup();await click('Review changes');
  const draft=structuredClone(latest),request=structuredClone(vi.mocked(teamSetupApi.rehearse).mock.calls[0][1]);
  await act(async()=>root.render(<Harness locked/>));
  await act(async()=>release(await rehearsalFixture(draft,request.expected_revision)));
  expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(1);expect(latest).toEqual(draft);
  expect([...element.querySelectorAll('input[type=checkbox]')].filter(visible)).toHaveLength(0);
  expect(button('Save team changes').disabled).toBe(true);expect(review).toBeNull();expect(saved).toBeNull();
  await act(async()=>root.render(<Harness/>));
  await wait(()=>expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(2));
  expect(vi.mocked(teamSetupApi.rehearse).mock.calls[1][1]).toEqual(request);
  expect(input('I reviewed these team changes').checked).toBe(false);
  expect(button('Save team changes').disabled).toBe(true);expect(review).toBeNull();expect(saved).toBeNull();
  await act(async()=>input('I reviewed these team changes').click());
  await click('Save team changes');expect(saved?.draft).toEqual(latest);expect(saved?.review).toEqual(review);
  expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(2);
});

it('waits for the current source inventory before automatically checking a policy change',async()=>{
  const {policySetupFixture,policyRehearsalFixture,resourcesFixture,usageFixture}=await import('./team-policy-test-fixture');
  let release!:(value:typeof resourcesFixture)=>void;
  vi.mocked(teamSetupApi.read).mockResolvedValue(await policySetupFixture());
  vi.mocked(teamSetupApi.resources).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  vi.mocked(teamSetupApi.usage).mockResolvedValue(usageFixture);
  vi.mocked(teamSetupApi.rehearse).mockImplementation(async(_,body)=>policyRehearsalFixture(body.configuration,body.expected_revision));
  await mount();await click('Team preferences');await click('AI work limit');await click('Add attempt limit to draft');
  await click('Done editing');await click('← Back');await click('Review changes');
  expect(teamSetupApi.rehearse).not.toHaveBeenCalled();expect(review).toBeNull();
  await act(async()=>release(resourcesFixture));
  await wait(()=>expect(teamSetupApi.rehearse).toHaveBeenCalledTimes(1));
  expect(vi.mocked(teamSetupApi.rehearse).mock.calls[0][1]).toMatchObject({scenario_id:'team_policy_setup.v1',configuration:{model_work:{version:1,max_attempts_per_24h:0}}});
  expect(input('I reviewed these team changes').checked).toBe(false);expect(saved).toBeNull();
});
