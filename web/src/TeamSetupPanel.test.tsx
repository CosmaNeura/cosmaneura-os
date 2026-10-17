import {act,useState} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {TeamSetupPanel,type ReviewedTeamDraft} from "./TeamSetupPanel";
import {ProviderTeamSettings} from "./ProviderTeamSettings";
import {teamSetupApi} from "./team-setup-api";
import {teamFixture,catalogFixture,projectionFixture,rehearsalFixture} from "./team-setup-test-fixture";
import {setupChange,applyPreset} from "./team-setup-request";
import {WorkspaceApiError,type TeamConfiguration,type TeamSaveInput} from "./workspace-api";
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>("node:crypto");
vi.mock('./team-setup-api',()=>({teamSetupApi:{read:vi.fn(),rehearse:vi.fn()}}));
const access={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
let root:Root,element:HTMLDivElement,latest:TeamConfiguration,saved:TeamSaveInput|undefined,accessLost:ReturnType<typeof vi.fn>,approval:ReviewedTeamDraft|null;
function Harness({initial=teamFixture().configuration}:{initial?:TeamConfiguration}){
  const [team,setTeam]=useState(()=>teamFixture()),[draft,setDraft]=useState(initial),[review,setReview]=useState<ReviewedTeamDraft|null>(null),[selected,setSelected]=useState('scribe');
  latest=draft;approval=review;
  return <><TeamSetupPanel identity={access} team={team} draft={draft} setDraft={setDraft} locked={false}
    onCurrentTeam={value=>setTeam(value)} onReviewChange={setReview} onAccessLost={accessLost}/>
    <ProviderTeamSettings team={team} draft={draft} setDraft={setDraft} selected={selected} setSelected={setSelected} locked={false} setupAvailable={true}
      reviewRequired={setupChange(team.configuration,draft)&&!review} onClose={()=>{}} onSave={()=>{saved={expected_revision:team.revision,idempotency_key:'invented-save',configuration:draft,...(review?{setup_review:review.review}:{})};}}/></>;
}
const button=(label:string)=>[...element.querySelectorAll('button')].find(b=>b.textContent?.trim()===label)!;
async function click(label:string){const b=button(label);expect(b,label).toBeTruthy();expect(b.disabled,label).toBe(false);await act(async()=>b.click());}
async function choose(label:string){const b=[...element.querySelectorAll('.team-preset-options button')].find(b=>b.querySelector('strong')?.textContent===label) as HTMLButtonElement;expect(b).toBeTruthy();await act(async()=>b.click());}
async function run(){await click("Check team settings");await vi.waitFor(async()=>{await act(async()=>{});expect(element.querySelector(".team-rehearsal input[type=checkbox]")).toBeTruthy();});}
async function checkReview(){const box=element.querySelector<HTMLInputElement>('.team-rehearsal input[type=checkbox]')!;expect(box).toBeTruthy();await act(async()=>box.click());}
async function rename(name:string){const input=element.querySelector<HTMLInputElement>('.team-settings-form input')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,name);input.dispatchEvent(new Event('input',{bubbles:true}));});}
async function mount(initial?:TeamConfiguration){root=createRoot(element);await act(async()=>root.render(<Harness initial={initial}/>));}
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();saved=undefined;approval=null;accessLost=vi.fn();element=document.createElement('div');document.body.append(element);
  const team=teamFixture();vi.mocked(teamSetupApi.read).mockResolvedValue({team,catalog:catalogFixture(),setup:await projectionFixture(team.configuration)});
  vi.mocked(teamSetupApi.rehearse).mockImplementation(async(_,body)=>rehearsalFixture(body.configuration,body.expected_revision));
});
afterEach(async()=>{if(root)await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();});
it('previews reusable groups, retains UUIDs, and requires a human review after invented rehearsal before saving changed capabilities',async()=>{
  await mount();await choose('Front desk');expect(latest.bots).toHaveLength(4);await click('Add Front desk to draft');const addresses=latest.bots.map(b=>b.instance_id??b.role);
  await choose('Front desk');expect(button('Add Front desk to draft').disabled).toBe(true);expect(latest.bots.map(b=>b.instance_id??b.role)).toEqual(addresses);
  expect(button('Save team settings').disabled).toBe(true);await run();expect(button('Save team settings').disabled).toBe(true);
  expect(element.textContent).toContain('Capabilities with these settings');expect(element.textContent).not.toContain('invented cases');expect(element.textContent).toContain('Inbox operations remains unavailable');
  expect(element.textContent).toContain('Each action checks its required sources and permissions again');await checkReview();await click('Save team settings');
  expect(saved?.setup_review).toEqual((await rehearsalFixture(latest)).setup_review);expect(saved?.configuration.bots.map(b=>b.instance_id??b.role)).toEqual(addresses);
  expect(vi.mocked(teamSetupApi.rehearse)).toHaveBeenCalledOnce();
});
it('invalidates review after edits, prerequisite refresh and component restart without persisting the checkbox',async()=>{
  await mount();await choose('Front desk');await click('Add Front desk to draft');await run();await checkReview();expect(approval).not.toBeNull();
  await rename('My Scribe');expect(approval).toBeNull();expect(button('Save team settings').disabled).toBe(true);
  await run();await checkReview();await click('Refresh setup prerequisites');expect(approval).toBeNull();expect(element.querySelector('.team-rehearsal input[type=checkbox]')).toBeNull();
  const draft=structuredClone(latest);await act(async()=>root.unmount());await mount(draft);expect(latest).toEqual(draft);expect(approval).toBeNull();expect(button('Save team settings').disabled).toBe(true);
});
it('does not overwrite an edit made while an invented rehearsal is returning',async()=>{
  let resolve!:(value:Awaited<ReturnType<typeof rehearsalFixture>>)=>void;vi.mocked(teamSetupApi.rehearse).mockImplementation(()=>new Promise(r=>{resolve=r;}));
  await mount();await choose('Front desk');await click('Add Front desk to draft');const sent=structuredClone(latest);await click('Check team settings');await rename('Edited during rehearsal');
  await act(async()=>resolve(await rehearsalFixture(sent)));expect(latest.bots[0].name).toBe('Edited during rehearsal');expect(approval).toBeNull();expect(element.textContent).not.toContain('Settings checked');
});
it('hides setup on an older backend while retaining the ordinary settings form and its unsent fields',async()=>{
  vi.mocked(teamSetupApi.read).mockRejectedValue(new WorkspaceApiError(404));const draft=teamFixture().configuration;draft.bots[0].name='';
  await mount(draft);expect(element.querySelector('.team-setup')).toBeNull();expect(element.querySelector('.team-settings')).toBeTruthy();expect(latest.bots[0].name).toBe('');expect(accessLost).not.toHaveBeenCalled();
});
it.each([401,403,426])('routes unsupported or revoked setup status %s to private-view withholding',async status=>{
  const error=new WorkspaceApiError(status);vi.mocked(teamSetupApi.read).mockRejectedValue(error);await mount();expect(accessLost).toHaveBeenCalledWith(error);expect(latest.bots).toHaveLength(4);
});
it('labels a blocked AI answer and private assignment without a misleading enabled badge',async()=>{
  const config=teamFixture().configuration;config.bots[3].blocked_capabilities=['model_answer'];const team=teamFixture(config);
  team.members[3].capabilities=[{key:'assistant.answer',label:'AI answer',state:'enabled',connector:'Model runtime',contract:null},{key:'workspace.draft.handoff',label:'Private assignment',state:'enabled',connector:'Workspace',contract:null}];
  root=createRoot(element);await act(async()=>root.render(<ProviderTeamSettings team={team} draft={config} setDraft={()=>{}} selected='chief' setSelected={()=>{}} locked={false} setupAvailable onSave={()=>{}} onClose={()=>{}}/>));
  const list=element.querySelector('.team-capability-list')!;expect(list.textContent?.match(/Blocked by your settings/g)).toHaveLength(2);expect(list.textContent).not.toContain('Runtime available');
});

it('requires review for zero attempt limits and explicit source restrictions, removal, and inherited access',async()=>{
 const {policySetupFixture,policyRehearsalFixture,resourcesFixture,usageFixture}=await import('./team-policy-test-fixture');
 Object.assign(teamSetupApi,{resources:vi.fn().mockResolvedValue(resourcesFixture),usage:vi.fn().mockResolvedValue(usageFixture)});
 vi.mocked(teamSetupApi.read).mockResolvedValue(await policySetupFixture());vi.mocked(teamSetupApi.rehearse).mockImplementation(async(_,body)=>policyRehearsalFixture(body.configuration,body.expected_revision));
 await mount();await click('Add attempt limit to draft');expect(latest.model_work).toEqual({version:1,max_attempts_per_24h:0});expect(element.textContent).toContain('Zero pauses new model work');expect(button('Save team settings').disabled).toBe(true);
 await click('Restrict Scribe sources');expect(latest.bots[0].resources?.allowed).toEqual([]);
 const select=[...element.querySelectorAll('label')].find(l=>l.textContent?.includes('Saved intake preparation for Scribe'))!.querySelector('select')!;
 await act(async()=>{select.value=resourcesFixture.resources[0].resource_ref;select.dispatchEvent(new Event('change',{bubbles:true}));});expect(latest.bots[0].resources?.allowed).toEqual([{purpose:'core_preparation',resource_ref:'d'.repeat(64)}]);
 await run();expect(element.textContent).toContain('Capabilities with these settings');expect(element.textContent).not.toContain('invented cases');await checkReview();expect(approval?.review.catalog_version).toBe(5);
 await click('Remove team attempt limit from draft');expect(latest).not.toHaveProperty('model_work');expect(approval).toBeNull();expect(button('Save team settings').disabled).toBe(true);
 await click('Use inherited source checks for Scribe');expect(latest.bots[0]).not.toHaveProperty('resources');expect(element.textContent).toContain('They do not grant connector access');
});
it('retains an unavailable saved source across refresh and ordinary edits without silently inheriting access',async()=>{
 const {policySetupFixture,policyRehearsalFixture,resourcesFixture,usageFixture}=await import('./team-policy-test-fixture');const config=teamFixture().configuration;
 config.bots[0].resources={version:1,allowed:[{purpose:'core_preparation',resource_ref:'f'.repeat(64)}]};
 Object.assign(teamSetupApi,{resources:vi.fn().mockResolvedValue(resourcesFixture),usage:vi.fn().mockResolvedValue(usageFixture)});
 vi.mocked(teamSetupApi.read).mockResolvedValue(await policySetupFixture(config));vi.mocked(teamSetupApi.rehearse).mockImplementation(async(_,body)=>policyRehearsalFixture(body.configuration,body.expected_revision));
 await mount(config);expect(element.textContent).toContain('Selected source unavailable');await rename('My Scribe');await run();expect(latest.bots[0].resources?.allowed[0].resource_ref).toBe('f'.repeat(64));
 await checkReview();await click('Refresh setup prerequisites');expect(approval).toBeNull();expect(latest.bots[0].resources?.allowed[0].resource_ref).toBe('f'.repeat(64));expect(element.textContent).toContain('never replaced with inherited access automatically');
});
it('rejects an unsaved stale source binding before rehearsal and retains it for correction when inventory fails',async()=>{
 const {policySetupFixture,resourcesFixture,usageFixture}=await import('./team-policy-test-fixture');const config=teamFixture().configuration;
 config.bots[0].resources={version:1,allowed:[{purpose:'core_preparation',resource_ref:'f'.repeat(64)}]};
 Object.assign(teamSetupApi,{resources:vi.fn().mockResolvedValue(resourcesFixture),usage:vi.fn().mockResolvedValue(usageFixture)});vi.mocked(teamSetupApi.read).mockResolvedValue(await policySetupFixture());
 await mount(config);await click('Check team settings');expect(teamSetupApi.rehearse).not.toHaveBeenCalled();expect(element.textContent).toContain('Refresh source choices');
 vi.mocked(teamSetupApi.resources).mockRejectedValue(new WorkspaceApiError(503));await click('Refresh setup prerequisites');expect(latest.bots[0].resources?.allowed[0].resource_ref).toBe('f'.repeat(64));expect(element.textContent).toContain('Retained source restrictions remain in place');
});

it('adds Membership/Billing review to an existing team draft without saving or replacing its coworker',async()=>{
 const {policySetupFixture}=await import('./team-policy-test-fixture');
 const initial=applyPreset(teamFixture().configuration,catalogFixture(),'practice_manager');
 const address=initial.presets!.find(p=>p.preset_id==='practice_manager')!.slots.membership_billing;
 const before=initial.bots.find(b=>b.instance_id===address)!;before.name='Membership helper';before.blocked_capabilities=['model_answer'];
 vi.mocked(teamSetupApi.read).mockResolvedValue(await policySetupFixture(initial));
 await mount(initial);await choose('Practice Manager');await click('Add Membership/Billing review skill to team draft');
 expect(latest.presets!.find(p=>p.preset_id==='practice_manager')!.version).toBe(2);
 expect(latest.bots.find(b=>b.instance_id===address)).toMatchObject({name:'Membership helper',blocked_capabilities:['model_answer'],skills:['membership_review'],enabled:true});
 expect(saved).toBeUndefined();expect(approval).toBeNull();expect(button('Save team settings').disabled).toBe(true);
});
