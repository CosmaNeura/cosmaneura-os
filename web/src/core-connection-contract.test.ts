import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/core-connection.json';
import {coreDigest,validateCoreConnection,type CoreConnectionCommand} from './core-connection-contract';

beforeEach(()=>vi.setSystemTime(new Date(fixture.connection.response.discovery.checked_at)));
afterEach(()=>vi.useRealTimers());
it('accepts actual signed OS account confirmation and appointment envelopes',async()=>{
  for(const item of Object.values(fixture))await expect(validateCoreConnection(item.response,item.command as CoreConnectionCommand)).resolves.toEqual(item.response);
});
it.each(['request_nonce','connection_sha256','source_sha256','timezone_known','patient_ref'])('refuses a changed %s before displaying a patient',async(field)=>{
  const item=structuredClone(fixture.encounters);
  if(field==='request_nonce')item.response.discovery.request_nonce=crypto.randomUUID();
  if(field==='connection_sha256')item.response.discovery.connection.connection_sha256='0'.repeat(64);
  if(field==='source_sha256')item.response.discovery.encounters[0].source_sha256='0'.repeat(64);
  if(field==='timezone_known')item.response.discovery.encounters[0].appointment.timezone_known=true;
  if(field==='patient_ref')item.response.discovery.encounters[0].patient.patient_ref='patient_00000000000000000000000002';
  await expect(validateCoreConnection(item.response,item.command as CoreConnectionCommand)).rejects.toThrow();
});
it('preserves unknown source time zones and rejects patient data added to a connection response',async()=>{
  const result=await validateCoreConnection(fixture.encounters.response,fixture.encounters.command as CoreConnectionCommand);
  expect(result.discovery.encounters[0].appointment.appointment_date).toBe('2026-09-23T09:00:00');
  const extra={...fixture.connection.response,diagnosis:'Invented unwanted field'};
  await expect(validateCoreConnection(extra,fixture.connection.command as CoreConnectionCommand)).rejects.toThrow();
});
it('rejects a response that moves an appointment outside the requested dates even with a matching hash',async()=>{
  const item=structuredClone(fixture.encounters),entry=item.response.discovery.encounters[0];
  entry.appointment.appointment_date='2026-10-23T09:00:00';
  const {source_sha256:_,...body}=entry;entry.source_sha256=await coreDigest(body);
  await expect(validateCoreConnection(item.response,item.command as CoreConnectionCommand)).rejects.toThrow();
});
