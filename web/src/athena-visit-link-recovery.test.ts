import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/athena-visit-links.json';
import {coreDigest} from './core-connection-contract';
import {type AthenaVisitLinkCommand,validateAthenaVisitLinkResult} from './athena-visit-link-api';
import {ATHENA_VISIT_RECOVERY_BYTES,AthenaVisitRecoverySession,athenaVisitStatusCommand,prepareAthenaVisitRecovery,validateAthenaVisitRecovery,
 type AthenaVisitRecoveryAccess,type AthenaVisitRecoveryRecord,type AthenaVisitRecoveryScope} from './athena-visit-link-recovery';

const scope:AthenaVisitRecoveryScope={box_id:'00000000-0000-4000-8000-000000000011',owner_id:'00000000-0000-4000-8000-000000000012',recovery_scope:'a'.repeat(64)};
beforeEach(()=>{vi.setSystemTime(new Date(fixture.preview.response.athena_visit_link.checked_at));});
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});
async function preview(operation:'link'|'unlink'='link',key?:string){
 const f=structuredClone(operation==='link'?fixture.preview:fixture.unlink_preview),command=f.command as AthenaVisitLinkCommand;
 if(key)command.command_key=key;
 const d=f.response.athena_visit_link;
 d.checked_at=new Date().toISOString();d.command_key=command.command_key!;
 const {request_nonce:_nonce,action:_action,...fields}=command;
 d.command_sha256=await coreDigest({...fields,action:operation,expected_actor_ref:d.connection.actor_ref,expected_tenant_ref:d.connection.tenant_ref,plan_sha256:d.plan_sha256,confirmed:true});
 return {command,response:f.response};
}
function reply(command:AthenaVisitLinkCommand,missing=false){
 const f=structuredClone(command.action==='athena_visit_unlink'?fixture.unlink:command.action==='athena_visit_link'?fixture.link:missing?fixture.not_found:fixture.status);
 f.response.action=command.action;
 const d=f.response.athena_visit_link;
 d.action=command.action.slice('athena_visit_'.length);d.checked_at=new Date().toISOString();d.request_nonce=command.request_nonce;d.command_key=command.command_key!;
 if(command.action==='athena_visit_status')d.command_sha256=command.command_sha256!;
 return f.response;
}
function harness(initial:AthenaVisitRecoveryRecord|null=null){
 let stored:unknown=structuredClone(initial),current=true;
 const events:string[]=[];
 const access:AthenaVisitRecoveryAccess={authorize:vi.fn(async()=>{events.push('authorize');}),current:()=>current,
  load:vi.fn(async()=>{events.push('load');return structuredClone(stored);}),
  persist:vi.fn(async value=>{events.push(value.resolution?'resolved':'pending');stored=structuredClone(value);})};
 const read=vi.fn(async(command:AthenaVisitLinkCommand)=>{events.push(command.action);return reply(command);});
 const session=new AthenaVisitRecoverySession(scope,access,read);
 return {access,read,session,events,stored:()=>structuredClone(stored),changeScope:()=>{current=false;},replace:(value:unknown)=>{stored=value;}};
}
async function pending(operation:'link'|'unlink'='link'){
 const p=await preview(operation);return prepareAthenaVisitRecovery(scope,p.command,p.response,true);
}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return {promise,resolve};}

describe('immutable, metadata-only recovery records',()=>{
 it.each(['link','unlink'] as const)('derives %s target from a fresh valid review and excludes private display fields',async operation=>{
  const record=await pending(operation),text=JSON.stringify(record);
  expect(await validateAthenaVisitRecovery(record,scope)).toEqual(record);
  expect(record.target.operation).toBe(operation);expect(record.resolution).toBeNull();
  expect(new TextEncoder().encode(text).length).toBeLessThan(ATHENA_VISIT_RECOVERY_BYTES);
  for(const forbidden of ['Invented patient','Invented practice','Invented office','display_name','practice_label','department_label','Bearer','token','encounter'])expect(text).not.toContain(forbidden);
  expect(record.request.request_nonce).not.toBe(operation==='link'?fixture.preview.command.request_nonce:fixture.unlink_preview.command.request_nonce);
 });
 it.each(['box_id','owner_id','recovery_scope'] as const)('rejects a recovered %s belonging to another scope',async field=>{
  const record=await pending(),other={...scope,[field]:field==='recovery_scope'?'b'.repeat(64):crypto.randomUUID()};
  await expect(validateAthenaVisitRecovery(record,other)).rejects.toMatchObject({code:'invalid'});
 });
 it.each(['command','target','binding','extra','resolution','oversize'] as const)('refuses retained %s corruption',async fault=>{
  const record=await pending();
  if(fault==='command')record.request.account_sha256='f'.repeat(64);
  if(fault==='target'&&record.target.operation==='link')record.target.patient_ref='patient_00000000000000000000000002';
  if(fault==='binding')record.binding.actor_ref='authority_actor_00000000000000000000000002';
  if(fault==='extra')Object.assign(record,{private_text:'invented secret'});
  if(fault==='resolution')record.resolution={state:'linked',checked_at:new Date().toISOString(),link_ref:'athena_visit_link_00000000000000000000000001'};
  if(fault==='oversize')Object.assign(record,{private_text:'x'.repeat(8193)});
  await expect(validateAthenaVisitRecovery(record,scope)).rejects.toMatchObject({code:'invalid'});
 });
 it.each(['unchecked','stale','wrong_patient','extra_text'] as const)('does not prepare from an %s preview',async fault=>{
  const p=await preview();
  if(fault==='stale')p.response.athena_visit_link.checked_at=new Date(Date.now()-31000).toISOString();
  if(fault==='wrong_patient')p.response.athena_visit_link.encounter!.patient.patient_ref='patient_00000000000000000000000002';
  if(fault==='extra_text')Object.assign(p.command,{note:'invented note'});
  await expect(prepareAthenaVisitRecovery(scope,p.command,p.response,fault!=='unchecked')).rejects.toThrow();
 });
 it('freezes input data before asynchronous validation',async()=>{
  const p=await preview(),preparation=prepareAthenaVisitRecovery(scope,p.command,p.response,true);
  p.command.account_sha256='f'.repeat(64);p.response.athena_visit_link.encounter!.patient.patient_ref='patient_00000000000000000000000002';
  const record=await preparation;
  expect(record.request.account_sha256).toBe(fixture.preview.command.account_sha256);
  expect(record.target).toMatchObject({patient_ref:fixture.preview.response.athena_visit_link.encounter!.patient.patient_ref});
 });
 it('preserves original mutation nonce while every status read receives a fresh nonce',async()=>{
  const record=await pending(),original=structuredClone(record.request),a=await athenaVisitStatusCommand(record,scope),b=await athenaVisitStatusCommand(record,scope);
  expect(record.request).toEqual(original);expect(new Set([record.request.request_nonce,a.request_nonce,b.request_nonce]).size).toBe(3);
  expect(a).toMatchObject({action:'athena_visit_status',command_key:record.request.command_key,command_sha256:record.command_sha256,account_sha256:record.request.account_sha256,connection_sha256:record.request.connection_sha256});
  expect(a).not.toHaveProperty('source');expect(a).not.toHaveProperty('confirmed');
 });
});

describe('persist-before-dispatch and exact recovery',()=>{
 it('stores pending metadata before a mutation and resolution before exposing its result',async()=>{
  const h=harness(),p=await preview();
  const result=await h.session.submit(p.command,p.response,true);
  expect(result.encounter?.patient.display_name).toBe('Invented patient');
  expect(h.events.indexOf('pending')).toBeLessThan(h.events.indexOf('athena_visit_link'));
  expect(h.events.indexOf('resolved')).toBeGreaterThan(h.events.indexOf('athena_visit_link'));
  expect(h.read).toHaveBeenCalledTimes(1);expect(h.session.snapshot()?.resolution?.state).toBe('linked');
  expect(JSON.stringify(h.stored())).not.toContain('Invented patient');
 });
 it('retains the clicked review while journal authorization is awaiting',async()=>{
  const h=harness(),p=await preview(),gate=deferred<void>();vi.mocked(h.access.authorize).mockReturnValueOnce(gate.promise);
  const operation=h.session.submit(p.command,p.response,true);
  p.command.account_sha256='f'.repeat(64);p.response.athena_visit_link.encounter!.patient.patient_ref='patient_00000000000000000000000002';
  gate.resolve();await operation;
  expect(h.read.mock.calls[0][0].account_sha256).toBe(fixture.preview.command.account_sha256);
  expect(h.session.snapshot()?.target).toMatchObject({patient_ref:fixture.preview.response.athena_visit_link.encounter!.patient.patient_ref});
 });
 it.each(['link','unlink'] as const)('restores a lost %s result after unmount and issues only exact status',async operation=>{
  const h=harness(),p=await preview(operation);
  h.read.mockRejectedValueOnce(new Error('invented private transport detail'));
  await expect(h.session.submit(p.command,p.response,true)).rejects.toMatchObject({code:'unavailable'});
  const original=h.session.snapshot()!;h.session.close();
  const restored=new AthenaVisitRecoverySession(scope,h.access,h.read);
  expect(await restored.restore()).toEqual(original);expect(h.read).toHaveBeenCalledTimes(1);
  h.read.mockImplementationOnce(async command=>{
   const value=reply(command);
   if(operation==='unlink')Object.assign(value.athena_visit_link,{state:'removed',operation:'unlink',link_ref:original.request.link_ref,encounter:null});
   return value;
  });
  await restored.check();
  expect(h.read).toHaveBeenCalledTimes(2);
  expect(h.read.mock.calls[1][0]).toMatchObject({action:'athena_visit_status',command_key:original.request.command_key,command_sha256:original.command_sha256});
  expect(h.read.mock.calls[1][0].request_nonce).not.toBe(original.request.request_nonce);
  expect((await restored.restore())?.resolution).not.toBeNull();expect(h.read).toHaveBeenCalledTimes(2);
 });
 it('does not expose a clinical projection from restored resolution metadata',async()=>{
  const h=harness(),p=await preview();await h.session.submit(p.command,p.response,true);h.session.close();
  const restored=new AthenaVisitRecoverySession(scope,h.access,h.read),record=await restored.restore();
  expect(record?.resolution?.state).toBe('linked');expect(record).not.toHaveProperty('encounter');expect(h.read).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(record)).not.toContain('display_name');
 });
 it('blocks fresh mutations while an uncertain result remains pending',async()=>{
  const h=harness(await pending()),p=await preview('link',crypto.randomUUID());
  await expect(h.session.submit(p.command,p.response,true)).rejects.toMatchObject({code:'pending'});expect(h.read).not.toHaveBeenCalled();
 });
 it('requires a newly reviewed different key after a confirmed missing result',async()=>{
  const record=await pending(),h=harness(record),p=await preview();
  h.read.mockImplementationOnce(async command=>reply(command,true));
  expect((await h.session.check()).state).toBe('not_found');
  await expect(h.session.submit(p.command,p.response,true)).rejects.toMatchObject({code:'fresh_review_required'});
  expect(h.read).toHaveBeenCalledTimes(1);
  const fresh=await preview('link',crypto.randomUUID());
  h.read.mockImplementationOnce(async command=>{
   const value=reply(command),{request_nonce:_nonce,action:_action,...fields}=command,d=value.athena_visit_link;
   d.command_sha256=await coreDigest({...fields,action:'link',expected_actor_ref:d.connection.actor_ref,expected_tenant_ref:d.connection.tenant_ref});return value;
  });
  expect((await h.session.submit(fresh.command,fresh.response,true)).state).toBe('linked');
  expect(h.read.mock.calls[1][0].command_key).toBe(fresh.command.command_key);
 });
 it.each(['before_write','lost_write_reply'] as const)('does not dispatch when private persistence fails %s',async fault=>{
  const h=harness(),p=await preview();
  vi.mocked(h.access.persist).mockImplementationOnce(async value=>{if(fault==='lost_write_reply')h.replace(value);throw new Error('private storage detail');});
  await expect(h.session.submit(p.command,p.response,true)).rejects.toMatchObject({code:'storage_unavailable'});expect(h.read).not.toHaveBeenCalled();
  const restored=await h.session.restore();expect(restored===null).toBe(fault==='before_write');
  if(restored)expect(restored.resolution).toBeNull();
 });
 it('withholds a result if its durable resolution cannot be saved',async()=>{
  const h=harness(),p=await preview();
  vi.mocked(h.access.persist).mockImplementationOnce(async value=>h.replace(value)).mockRejectedValueOnce(new Error('storage gone'));
  await expect(h.session.submit(p.command,p.response,true)).rejects.toMatchObject({code:'storage_unavailable'});
  expect(h.read).toHaveBeenCalledTimes(1);expect((await h.session.restore())?.resolution).toBeNull();
 });
 it('makes no provider request if no pending or resolved metadata exists',async()=>{
  const h=harness();expect(await h.session.restore()).toBeNull();
  await expect(h.session.check()).rejects.toMatchObject({code:'fresh_review_required'});expect(h.read).not.toHaveBeenCalled();
 });
});

describe('scope and exact target fences',()=>{
 it.each(['journal','read'] as const)('withholds late work after scope changes during %s',async phase=>{
  const h=harness(),p=await preview();
  const waiting=deferred<void>(),entered=deferred<void>();
  if(phase==='journal')vi.mocked(h.access.persist).mockImplementationOnce(async value=>{h.replace(value);entered.resolve();await waiting.promise;});
  else h.read.mockImplementationOnce(async command=>{entered.resolve();await waiting.promise;return reply(command);});
  const operation=h.session.submit(p.command,p.response,true),rejected=expect(operation).rejects.toMatchObject({code:'scope_changed'});
  await entered.promise;h.changeScope();waiting.resolve();await rejected;
  expect(h.read).toHaveBeenCalledTimes(phase==='journal'?0:1);expect(()=>h.session.snapshot()).toThrow();
  expect((h.stored() as AthenaVisitRecoveryRecord).resolution).toBeNull();
 });
 it('blocks dispatch when closed during authorization, and refuses a concurrent call',async()=>{
  const h=harness(),p=await preview(),gate=deferred<void>();vi.mocked(h.access.authorize).mockReturnValueOnce(gate.promise);
  const first=h.session.submit(p.command,p.response,true),rejected=expect(first).rejects.toMatchObject({code:'scope_changed'});
  await expect(h.session.restore()).rejects.toMatchObject({code:'busy'});h.session.close();gate.resolve();await rejected;expect(h.read).not.toHaveBeenCalled();
 });
 it('blocks dispatch when fresh authority is denied after the journal write',async()=>{
  const h=harness(),p=await preview();
  vi.mocked(h.access.persist).mockImplementationOnce(async value=>{h.replace(value);vi.mocked(h.access.authorize).mockRejectedValueOnce(new Error('denied'));});
  await expect(h.session.submit(p.command,p.response,true)).rejects.toMatchObject({code:'scope_changed'});expect(h.read).not.toHaveBeenCalled();
  expect((h.stored() as AthenaVisitRecoveryRecord).resolution).toBeNull();
 });
 it.each(['appointment','patient','operation','account','connection','actor','tenant','nonce','command_hash','stale'] as const)('rejects a status projection with the wrong %s without replacing pending metadata',async fault=>{
  const record=await pending(),h=harness(record);
  h.read.mockImplementationOnce(async command=>{
   const value=reply(command),d=value.athena_visit_link,e=d.encounter!;
   if(fault==='appointment')e.appointment.appointment_ref='appointment_00000000000000000000000002';
   if(fault==='patient'){e.patient.patient_ref='patient_00000000000000000000000002';e.appointment.patient_ref=e.patient.patient_ref;}
   if(fault==='operation')d.operation='unlink';
   if(fault==='account')d.account.account_sha256='f'.repeat(64);
   if(fault==='connection')d.connection.connection_sha256='f'.repeat(64);
   if(fault==='actor')d.connection.actor_ref='authority_actor_00000000000000000000000002';
   if(fault==='tenant')d.connection.tenant_ref='authority_tenant_00000000000000000000000002';
   if(fault==='nonce')d.request_nonce=crypto.randomUUID();
   if(fault==='command_hash')d.command_sha256='f'.repeat(64);
   if(fault==='stale')d.checked_at=new Date(Date.now()-31000).toISOString();
   if(fault==='appointment'||fault==='patient'){const {source_sha256:_old,...body}=e;e.source_sha256=await coreDigest(body);await validateAthenaVisitLinkResult(value,command);}
   return value;
  });
  await expect(h.session.check()).rejects.toMatchObject({code:'result_unverified'});expect(h.stored()).toEqual(record);expect(h.access.persist).not.toHaveBeenCalled();
 });
 it('rejects the wrong removal link even when the status contract itself validates',async()=>{
  const record=await pending('unlink'),h=harness(record);
  h.read.mockImplementationOnce(async command=>{const value=reply(command);Object.assign(value.athena_visit_link,{state:'removed',operation:'unlink',link_ref:'athena_visit_link_00000000000000000000000002',encounter:null});await validateAthenaVisitLinkResult(value,command);return value;});
  await expect(h.session.check()).rejects.toMatchObject({code:'result_unverified'});expect(h.stored()).toEqual(record);
 });
 it('accepts a newer fresh projection only for the same reviewed patient and visit',async()=>{
  const h=harness(await pending());
  h.read.mockImplementationOnce(async command=>{const value=reply(command),e=value.athena_visit_link.encounter!;e.patient.display_name='Invented updated name';const {source_sha256:_old,...body}=e;e.source_sha256=await coreDigest(body);return value;});
  const result=await h.session.check();expect(result.encounter?.patient.display_name).toBe('Invented updated name');expect(JSON.stringify(h.stored())).not.toContain('Invented updated name');
 });
});
