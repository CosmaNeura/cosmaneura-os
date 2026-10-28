import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/athena-visit-links.json';
import {AthenaVisitLinkPanel} from './AthenaVisitLinkPanel';
import {coreConnectionApi} from './core-connection-api';
import {coreDigest} from './core-connection-contract';
import {validateAthenaVisitLinkCommand,validateAthenaVisitLinkResult,type AthenaVisitLinkCommand,type AthenaVisitLinkObservation} from './athena-visit-link-api';
import type {AthenaAccount,AthenaAppointment} from './athena-connection-contract';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
let host:HTMLDivElement,root:Root;
let fixtureReplies:Promise<never>[]=[];
async function settle(){await act(async()=>{await Promise.all(fixtureReplies.splice(0));});}
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const props={connection:fixture.lookup.response.athena_visit_link.connection,account:fixture.lookup.response.athena_visit_link.account as AthenaAccount,source:fixture.lookup.response.athena_visit_link.source as AthenaAppointment,selection:fixture.lookup.command.source};
const reply=(name:Exclude<keyof typeof fixture,'encounters'>)=>fixture[name].response as never;
const respond=(name:Exclude<keyof typeof fixture,'encounters'>,edit?:(value:AthenaVisitLinkObservation)=>void|Promise<void>)=>(_who:unknown,input:unknown)=>{const task=(async()=>{
 const command=input as AthenaVisitLinkCommand,value=structuredClone(fixture[name].response),d=value.athena_visit_link;
 validateAthenaVisitLinkCommand(command);
 Object.assign(d,{checked_at:new Date().toISOString(),request_nonce:command.request_nonce,command_key:command.command_key??null});
 if(command.command_key){
  const {request_nonce:_nonce,action,...values}=command;
  const operation=action==='athena_visit_preview'?'link':action==='athena_visit_unlink_preview'?'unlink':action.slice('athena_visit_'.length);
  const hash=operation==='status'?command.command_sha256:await coreDigest({...values,action:operation,expected_actor_ref:d.connection.actor_ref,expected_tenant_ref:d.connection.tenant_ref,...(action.endsWith('preview')?{plan_sha256:d.plan_sha256,confirmed:true}:{})});
  Object.assign(d,{command_sha256:hash});
 }
 await edit?.(d as unknown as AthenaVisitLinkObservation);
 return await validateAthenaVisitLinkResult(value,command) as never;
})();fixtureReplies.push(task);return task;
};
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();fixtureReplies=[];host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
const button=(label:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===label)!;
async function click(label:string){expect(button(label)).toBeDefined();await act(async()=>button(label).click());await settle();}
async function mount(who=identity,open=vi.fn(async()=>{}),changed=vi.fn()){await act(async()=>root.render(<AthenaVisitLinkPanel {...props} identity={who} onAccessLost={changed} onClose={()=>{}} onOpenNotebook={open}/>));await settle();}
async function review(){await click('Find Cosmaneura visits');await click('Review this visit');}
it('requires patient review, recovers a lost save without replay, and opens the linked notebook',async()=>{
 const open=vi.fn(async()=>{}),storage=vi.spyOn(Storage.prototype,'setItem');
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(respond('lookup')).mockResolvedValueOnce(fixture.encounters as never).mockImplementationOnce(respond('preview')).mockRejectedValueOnce(new Error('lost reply')).mockImplementationOnce(respond('status'));
 await mount(identity,open);await review();expect(button('Save visit connection').disabled).toBe(true);
 expect(host.textContent).toContain('Invented patient');expect(host.textContent).toContain('Athena patient reference 9001');
 await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Save visit connection');
 expect(button('Close visit connection').disabled).toBe(true);expect(host.textContent).toContain('Check saved result');
 await click('Check saved result');await click('Open linked notebook');
 expect(open).toHaveBeenCalledWith(expect.objectContaining({action:'open',appointment_ref:fixture.link.command.appointment_ref,source_sha256:fixture.link.command.core_source_sha256}));
 expect(vi.mocked(coreConnectionApi.read).mock.calls.map(call=>call[1].action)).toEqual(['athena_visit_lookup','encounters','athena_visit_preview','athena_visit_link','athena_visit_status']);
 const commands=vi.mocked(coreConnectionApi.read).mock.calls.map(call=>call[1]);expect(commands[2]).toMatchObject({source:{offset:25},core_source_sha256:fixture.preview.command.core_source_sha256});
 expect(commands[4]).toMatchObject({command_key:(commands[3] as AthenaVisitLinkCommand).command_key});expect((commands[4] as AthenaVisitLinkCommand).command_sha256).toMatch(/^[a-f0-9]{64}$/);expect(storage).not.toHaveBeenCalled();
});
it('requires a separate review to remove a connection and retains its history',async()=>{
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(respond('linked_lookup')).mockImplementationOnce(respond('unlink_preview')).mockImplementationOnce(respond('unlink'));
 await mount();await click('Review removing connection');expect(button('Remove visit connection').disabled).toBe(true);
 await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Remove visit connection');
 expect(host.textContent).toContain('Its history is retained');expect(host.textContent).not.toContain('Open linked notebook');
 expect(vi.mocked(coreConnectionApi.read).mock.calls[2][1]).toMatchObject({action:'athena_visit_unlink',confirmed:true,link_ref:fixture.unlink.command.link_ref});
});
it('requires a fresh current-state check when the uncertain command was not found',async()=>{
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(respond('lookup')).mockResolvedValueOnce(fixture.encounters as never).mockImplementationOnce(respond('preview')).mockRejectedValueOnce(new Error('lost reply')).mockImplementationOnce(respond('not_found'));
 await mount();await review();await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Save visit connection');await click('Check saved result');
 expect(host.textContent).toContain('No saved result was found');expect(button('Find Cosmaneura visits')).toBeUndefined();expect(button('Save visit connection')).toBeUndefined();
});
it('does not display a late patient result after changing accounts',async()=>{
 let finish!:(value:never)=>void;
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockImplementationOnce(respond('lookup'));
 await mount();const signal=vi.mocked(coreConnectionApi.read).mock.calls[0][2];await mount({...identity,getToken:async()=>null});
 await act(async()=>finish(reply('linked_lookup')));expect(signal?.aborted).toBe(true);expect(host.textContent).not.toContain('Invented patient');expect(button('Open linked notebook')).toBeUndefined();
});
it('does not offer saving when patient correspondence needs review',async()=>{
 const conflict=structuredClone(fixture.preview.response);Object.assign(conflict.athena_visit_link,{state:'review_required',plan_sha256:null,command_sha256:null,operation:null});
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(respond('lookup')).mockResolvedValueOnce(fixture.encounters as never).mockResolvedValueOnce(conflict as never);
 await mount();await review();expect(host.textContent).toContain('needs review');expect(button('Save visit connection')).toBeUndefined();
});
it.each(['appointment','patient'] as const)('withholds a recovered notebook for a different reviewed %s and checks the same command again',async fault=>{
 const open=vi.fn(async()=>{});
 const changed=respond('status',async d=>{
  const encounter=d.encounter!;
  if(fault==='appointment')encounter.appointment.appointment_ref='appointment_00000000000000000000000002';
  else{encounter.patient.patient_ref='patient_00000000000000000000000002';encounter.appointment.patient_ref=encounter.patient.patient_ref;}
  const {source_sha256:_old,...content}=encounter;encounter.source_sha256=await coreDigest(content);
 });
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(respond('lookup')).mockResolvedValueOnce(fixture.encounters as never).mockImplementationOnce(respond('preview')).mockRejectedValueOnce(new Error('lost reply')).mockImplementationOnce(changed).mockImplementationOnce(respond('status'));
 await mount(identity,open);await review();await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Save visit connection');
 await click('Check saved result');expect(host.textContent).toContain('saved result could not be verified');expect(button('Open linked notebook')).toBeUndefined();expect(button('Close visit connection').disabled).toBe(true);expect(open).not.toHaveBeenCalled();
 await click('Check saved result');await click('Open linked notebook');expect(open).toHaveBeenCalledOnce();
 const commands=vi.mocked(coreConnectionApi.read).mock.calls.map(call=>call[1] as AthenaVisitLinkCommand);
 expect(commands.filter(c=>c.action==='athena_visit_link')).toHaveLength(1);
 expect(commands[5]).toMatchObject({command_key:commands[4].command_key,command_sha256:commands[4].command_sha256});
});
it('allows a fresh projection for the same reviewed patient and appointment after recovering the save',async()=>{
 const open=vi.fn(async()=>{});
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(respond('lookup')).mockResolvedValueOnce(fixture.encounters as never).mockImplementationOnce(respond('preview')).mockRejectedValueOnce(new Error('lost reply')).mockImplementationOnce(respond('status',async d=>{
  const encounter=d.encounter!;encounter.patient.display_name='Invented updated display name';
  const {source_sha256:_old,...content}=encounter;encounter.source_sha256=await coreDigest(content);
 }));
 await mount(identity,open);await review();await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Save visit connection');await click('Check saved result');
 expect(host.textContent).toContain('Invented updated display name');await click('Open linked notebook');
 expect(open).toHaveBeenCalledWith(expect.objectContaining({appointment_ref:fixture.link.command.appointment_ref}));
 expect(open.mock.calls[0]).not.toEqual([expect.objectContaining({source_sha256:fixture.link.command.core_source_sha256})]);
});
it.each(['operation','connection'] as const)('keeps a removal unresolved when its saved %s differs from the reviewed removal',async fault=>{
 const changed=respond('status',d=>{
  if(fault==='connection')Object.assign(d,{operation:'unlink',state:'removed',encounter:null,link_ref:'athena_visit_link_00000000000000000000000002'});
 });
 const removed=respond('status',d=>{Object.assign(d,{operation:'unlink',state:'removed',encounter:null,link_ref:fixture.unlink.command.link_ref});});
 vi.mocked(coreConnectionApi.read).mockImplementationOnce(respond('linked_lookup')).mockImplementationOnce(respond('unlink_preview')).mockRejectedValueOnce(new Error('lost reply')).mockImplementationOnce(changed).mockImplementationOnce(removed);
 await mount();await click('Review removing connection');await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Remove visit connection');await click('Check saved result');
 expect(host.textContent).toContain('saved result could not be verified');expect(button('Open linked notebook')).toBeUndefined();expect(button('Close visit connection').disabled).toBe(true);
 await click('Check saved result');expect(host.textContent).toContain('Its history is retained');expect(button('Check saved result')).toBeUndefined();
 expect(vi.mocked(coreConnectionApi.read).mock.calls.filter(call=>call[1].action==='athena_visit_unlink')).toHaveLength(1);
});
