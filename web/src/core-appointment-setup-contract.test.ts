import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/core-appointment-setup.json';
import wire from './__fixtures__/core-appointment-setup-os.json';
import {validateAppointmentSetupCommand,validateAppointmentSetupResult,type AppointmentSetupCommand} from './core-appointment-setup-contract';

beforeEach(()=>vi.setSystemTime(new Date(fixture.connect.response.appointment_setup.checked_at)));
afterEach(()=>vi.useRealTimers());
it('accepts the actual Core preview and committed result',async()=>{
  for(const item of Object.values(fixture)){
    await validateAppointmentSetupCommand(item.command as AppointmentSetupCommand);
    await expect(validateAppointmentSetupResult(item.response,item.command as AppointmentSetupCommand)).resolves.toEqual(item.response);
  }
});
it.each(['nonce','connection','plan','window','counts','outcome','stale','cursor','extra'])('refuses changed %s before showing success',async fault=>{
  const value=structuredClone(fixture.connect),d=value.response.appointment_setup;
  if(fault==='nonce')d.request_nonce=crypto.randomUUID();
  if(fault==='connection')d.connection.connection_sha256='0'.repeat(64);
  if(fault==='plan')d.plan_sha256='0'.repeat(64);
  if(fault==='window')d.window.end_date='2026-09-26';
  if(fault==='counts')d.eligible_count=26;
  if(fault==='outcome')d.connected_now_count=24;
  if(fault==='stale')d.checked_at='2000-01-01T00:00:00Z';
  if(fault==='cursor')d.next_cursor.appointment_date='2026-09-25T09:00:00';
  if(fault==='extra')Object.assign(d,{patient_name:'Unrequested invented name'});
  await expect(validateAppointmentSetupResult(value.response,value.command as AppointmentSetupCommand)).rejects.toThrow();
});
it('requires the exact reviewed plan and a bounded page',async()=>{
  for(const extra of [{plan_sha256:undefined},{expected_actor_ref:'untrusted'},{window:{start_date:'2026-09-24',end_date:'2026-12-01'}}])await expect(validateAppointmentSetupCommand({...fixture.connect.command,...extra} as AppointmentSetupCommand)).rejects.toThrow();
});

it('accepts the actual signed OS/Core HTTP observations',async()=>{
  for(const item of Object.values(wire)){
    vi.setSystemTime(new Date(item.response.appointment_setup.checked_at));
    await validateAppointmentSetupCommand(item.command as AppointmentSetupCommand);
    await expect(validateAppointmentSetupResult(item.response,item.command as AppointmentSetupCommand)).resolves.toEqual(item.response);
  }
});
