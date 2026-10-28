import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {athenaRehearsal} from './athena';
import {athenaDateWindow} from '../src/AthenaConnectionPanel';
import {coreConnectionApi} from '../src/core-connection-api';
import type {CoreConnectionCommand,CoreEncounter} from '../src/core-connection-contract';
import type {AthenaVisitLinkCommand} from '../src/athena-visit-link-api';
vi.mock('../src/workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Authorization':'Bearer invented'})}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const workspace={workspace_id:'00000000-0000-4000-8000-000000000001',appointment_id:'00000000-0000-4000-8000-000000000002'};
const nonce=()=>crypto.randomUUID();
async function receiver(reset=false){
 const port=await athenaRehearsal('invented-athena-date-test',reset,()=>workspace);
 vi.stubGlobal('fetch',async(input:string|URL|Request,init?:RequestInit)=>{
  const path=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href).pathname;
  const response=await port(path,init);if(!response)throw new Error('No external fixture passthrough');return response;
 });
}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_COSMAS_ENV','synth_os');
 vi.setSystemTime(new Date('2026-10-27T00:30:00Z'));sessionStorage.clear();history.replaceState(null,'','/');await receiver(true);
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();vi.unstubAllEnvs();history.replaceState(null,'','/');});
async function review(day=athenaDateWindow('America/New_York').start_date){
 const connection=(await coreConnectionApi.read(identity,{action:'connection',request_nonce:nonce()})).discovery!.connection!;
 const account=(await coreConnectionApi.read(identity,{action:'athena_connection',request_nonce:nonce(),connection_sha256:connection.connection_sha256})).athena_discovery.account!;
 const row=(await coreConnectionApi.read(identity,{action:'athena_appointments',request_nonce:nonce(),connection_sha256:connection.connection_sha256,account_sha256:account.account_sha256,start_date:day,end_date:day,offset:0})).athena_discovery.appointments[0];
 const end=new Date(day+'T00:00:00Z');end.setUTCDate(end.getUTCDate()+1);
 const encounter=(await coreConnectionApi.read(identity,{action:'encounters',request_nonce:nonce(),connection_sha256:connection.connection_sha256,window:{start_date:day,end_date:end.toISOString().slice(0,10)}})).discovery!.encounters[0];
 const command:AthenaVisitLinkCommand={action:'athena_visit_preview',request_nonce:nonce(),connection_sha256:connection.connection_sha256,account_sha256:account.account_sha256,command_key:nonce(),
  source:{start_date:day,end_date:day,offset:0,appointment_ref:row.appointment_ref,source_sha256:row.source_sha256},appointment_ref:encounter.appointment.appointment_ref,core_source_sha256:encounter.source_sha256};
 const preview=(await coreConnectionApi.read(identity,command)).athena_visit_link;
 return {encounter,command:{...command,action:'athena_visit_link' as const,request_nonce:nonce(),plan_sha256:preview.plan_sha256!,confirmed:true as const},hash:preview.command_sha256!};
}
const openCommand=(encounter:CoreEncounter):CoreConnectionCommand=>({action:'open',request_nonce:nonce(),connection_sha256:encounter.connection_sha256,appointment_ref:encounter.appointment.appointment_ref,source_sha256:encounter.source_sha256});
it.each(['2026-10-26','2026-11-03'])('opens the exact linked %s visit independently of the UTC date',async day=>{
 expect(athenaDateWindow('America/New_York').start_date).toBe('2026-10-26');expect(new Date().toISOString().slice(0,10)).toBe('2026-10-27');
 const selected=await review(day),linked=(await coreConnectionApi.read(identity,selected.command)).athena_visit_link.encounter!;
 expect(linked).toEqual(selected.encounter);
 const opened=await coreConnectionApi.read(identity,openCommand(linked));expect(opened.workspace).toEqual(workspace);expect(opened.discovery!.encounters).toEqual([linked]);
});
it('retains the selected visit through a lost link reply, UTC rollover and receiver reload',async()=>{
 const selected=await review();history.replaceState(null,'','/?scenario=athena-lost-link');
 await expect(coreConnectionApi.read(identity,selected.command)).rejects.toMatchObject({status:503});
 vi.setSystemTime(new Date('2026-10-29T00:30:00Z'));await receiver();
 const status=(await coreConnectionApi.read(identity,{action:'athena_visit_status',request_nonce:nonce(),connection_sha256:selected.command.connection_sha256,account_sha256:selected.command.account_sha256,
  command_key:selected.command.command_key,command_sha256:selected.hash})).athena_visit_link;
 expect(status.encounter).toEqual(selected.encounter);expect(status.applied).toBe(true);
 const opened=await coreConnectionApi.read(identity,openCommand(selected.encounter));expect(opened.discovery!.encounters).toEqual([selected.encounter]);
 const stats=(window as unknown as {athenaRehearsalStats:{actions:{action:string}[];externalCalls:number}}).athenaRehearsalStats;
 expect(stats.actions.map(value=>value.action)).toEqual(['athena_visit_status','open']);expect(stats.externalCalls).toBe(0);
});
it('keeps exact connection, appointment and source admission, and refuses an unlinked visit',async()=>{
 const selected=await review();await coreConnectionApi.read(identity,selected.command);const command=openCommand(selected.encounter);
 for(const change of [{connection_sha256:'f'.repeat(64)},{appointment_ref:'appointment_00000000000000000000000002'},{source_sha256:'f'.repeat(64)}])
  await expect(coreConnectionApi.read(identity,{...command,...change})).rejects.toMatchObject({status:409,code:'core_connection_changed'});
 const preview:AthenaVisitLinkCommand={action:'athena_visit_unlink_preview',request_nonce:nonce(),connection_sha256:selected.command.connection_sha256,account_sha256:selected.command.account_sha256,
  command_key:nonce(),link_ref:'athena_visit_link_00000000000000000000000001'};
 const result=(await coreConnectionApi.read(identity,preview)).athena_visit_link;
 await coreConnectionApi.read(identity,{...preview,action:'athena_visit_unlink',request_nonce:nonce(),plan_sha256:result.plan_sha256!,confirmed:true});
 await expect(coreConnectionApi.read(identity,command)).rejects.toMatchObject({status:409,code:'core_connection_changed'});
});
