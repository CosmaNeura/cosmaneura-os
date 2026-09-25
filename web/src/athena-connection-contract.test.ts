import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/athena-connection.json';
import {validateAthenaCommand,validateAthenaResult,type AthenaCommand} from './athena-connection-contract';
import {coreDigest} from './core-connection-contract';

beforeEach(()=>vi.setSystemTime(new Date(fixture.appointments.response.athena_discovery.checked_at)));
afterEach(()=>vi.useRealTimers());
it('validates the Core receiver projection and connection readiness separately',async()=>{
  for(const item of Object.values(fixture)){
    validateAthenaCommand(item.command as AthenaCommand);
    await expect(validateAthenaResult(item.response,item.command as AthenaCommand)).resolves.toEqual(item.response);
  }
});
it.each(['nonce','connection','account','digest','patient','status','timezone','pagination','stale','extra'])('refuses changed %s before displaying the schedule',async fault=>{
  const value=structuredClone(fixture.appointments),d=value.response.athena_discovery;
  if(fault==='nonce')d.request_nonce=crypto.randomUUID();
  if(fault==='connection')d.connection.connection_sha256='0'.repeat(64);
  if(fault==='account')d.account.account_sha256='0'.repeat(64);
  if(fault==='digest')d.appointments[0].source_sha256='0'.repeat(64);
  if(fault==='patient')d.appointments[0].patient_ref='9999';
  if(fault==='status')d.appointments[0].source_status='diagnosed';
  if(fault==='timezone')d.account.department_timezone='Invalid/Zone';
  if(fault==='pagination')Object.assign(d,{next_offset:1});
  if(fault==='stale')d.checked_at='2000-01-01T00:00:00Z';
  if(fault==='extra')Object.assign(d,{note:'Unrequested invented note'});
  await expect(validateAthenaResult(value.response,value.command as AthenaCommand)).rejects.toThrow();
});
it('rejects a correctly hashed observation outside the requested dates',async()=>{
  const value=structuredClone(fixture.appointments),d=value.response.athena_discovery,row=d.appointments[0];
  row.source_local_start='2026-10-24T09:30:00';
  const {source_sha256:_,...content}=row;
  row.source_sha256=await coreDigest({account_sha256:d.account.account_sha256,...content});
  await expect(validateAthenaResult(value.response,value.command as AthenaCommand)).rejects.toThrow();
});
it('requires a closed bounded command without vendor identifiers',()=>{
  for(const extra of [{provider_id:'701'},{offset:-1},{offset:true},{end_date:'2026-12-01'}])expect(()=>validateAthenaCommand({...fixture.appointments.command,...extra} as AthenaCommand)).toThrow();
});
