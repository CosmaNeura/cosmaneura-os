import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createPrivateRecordingIntent,createPrivateRecordingFinishIntent,parsePrivateRecordingReceipt,parseRecordingVisitBinding,privateRecordingApi,
  type PrivateRecordingIntent,type PrivateRecordingReceipt} from './private-recording-api';
import {vendorCanonical,vendorSha256} from './vendor-contract';
import type {ProviderTeam,Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
let team:ProviderTeam,workspace:Workspace,scope:string;
const identity={mode:'clerk_jwt' as const,getToken:vi.fn(async()=>'invented-token')};
const consent={modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:'2026-10-08T00:00:00.000Z'};
const json=(v:unknown)=>new Response(JSON.stringify(v),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
beforeEach(async()=>{
  vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
  vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','true');vi.stubGlobal('window',{location:{href:'http://localhost:5173'}});
  identity.getToken.mockClear();scope=await vendorSha256(new TextEncoder().encode(vendorCanonical({contract:'cosmas-private-drafts-v1',box_id:id(10),owner_id:id(11)})));
  team={revision:1,recovery_scope:scope,template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'',bots:[{role:'scribe',name:'Scribe',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[{role:'scribe',agent_id:id(12),name:'Scribe',initials:'S',description:'',prompt:'',capabilities:[]}]};
  workspace={id:id(1),appointment_id:null,label:'Private recording',revision:1,entries:[],work_candidates:[],private_draft:{title:'Private recording',state:'unlinked',link_receipt_id:null,linked_at:null}};
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();vi.unstubAllEnvs();});
const intent=()=>createPrivateRecordingIntent(team,workspace,id(2),consent,'2026-10-08T00:00:01.123Z');
const sha=(value:unknown)=>vendorSha256(new TextEncoder().encode(vendorCanonical(value)));
function receipt(v:PrivateRecordingIntent):PrivateRecordingReceipt {
  return {contract:'cosmas.private-recording.v1',custody:'local_device_metadata',recording_id:id(3),local_recording_id:id(2),workspace_id:id(1),workspace_revision:1,
    owner_id:id(11),box_id:id(10),agent_id:id(12),team_revision_id:id(13),recovery_scope:scope,attach_sha256:v.request_sha256,started_at:v.request.started_at,created_at:'2026-10-08T00:00:02Z',state:'unfinished',finish:null,link:null,upstream_capture_admitted:false,audio_uploaded:false,transcription_started:false};
}
it('binds an existing visit with independently verified source hashes while retaining the origin',async()=>{
  const v=await intent(),saved={...receipt(v),state:'finished' as const,finish:{receipt_id:id(4),request_sha256:'b'.repeat(64),manifest_sha256:'c'.repeat(64),chunks:2,frames:32000,ended_at:'2026-10-08T00:00:04Z'}};
  const command={idempotency_key:id(40),target_workspace_id:id(41),appointment_id:id(42),expected_target_revision:3,visit_confirmed:true as const};
  const request_sha256=await sha({contract:'cosmas.private-recording.visit-binding.v1',request:command});
  const binding={contract:'cosmas.private-recording.visit-binding.v1' as const,receipt_id:id(43),recording_id:saved.recording_id,origin_workspace_id:v.workspace_id,target_workspace_id:id(41),appointment_id:id(42),request:command,request_sha256,appointment_sha256:'a'.repeat(64),source_sha256:await sha({contract:'cosmas.private-recording.visit-source.v1',recording_id:saved.recording_id,origin_workspace_id:v.workspace_id,attach_sha256:saved.attach_sha256,finish_sha256:saved.finish.request_sha256,manifest_sha256:saved.finish.manifest_sha256,target_workspace_id:id(41),appointment_sha256:'a'.repeat(64),binding_request_sha256:request_sha256})};
  const fetcher=vi.fn(async(_input:unknown,_init?:RequestInit)=>json(binding));vi.stubGlobal('fetch',fetcher);
  expect(await privateRecordingApi.bindVisit(identity,v,team,saved,command)).toEqual(binding);
  expect(await privateRecordingApi.readVisitBinding(identity,v,team,saved)).toEqual(binding);
  expect(fetcher.mock.calls[0][0]).toBe(`http://127.0.0.1:8018/workspaces/${id(1)}/private-recordings/${id(3)}/visit-binding`);
  for(const altered of [{...binding,origin_workspace_id:id(99)},{...binding,target_workspace_id:id(99)},{...binding,source_sha256:'d'.repeat(64)},{...binding,request:{...command,appointment_id:id(99)}}])await expect(parseRecordingVisitBinding(altered,saved)).rejects.toThrow();
  expect(saved.workspace_id).toBe(id(1));
});
it('matches actual Python canonical timestamp and SHA before any token or HTTP',async()=>{
  const v=await intent();v.request.idempotency_key=id(1);
  const canonical=vendorCanonical({contract:'cosmas.private-recording.attach.v1',request:v.request});
  expect(await vendorSha256(new TextEncoder().encode(canonical))).toBe('077f423589fdfddf10f6ae63e715c832f492f503c818fe2ce5b3292fceff3a3e');
  expect(v.request.started_at).toBe('2026-10-08T00:00:01.123000Z');expect(v.request.consent.granted_at).toBe('2026-10-08T00:00:00Z');expect(identity.getToken).not.toHaveBeenCalled();
});
it('uses signed bounded metadata requests and exact resolve/read with no extra account fetch or retry',async()=>{
  const v=await intent(),saved=receipt(v),fetcher=vi.fn().mockResolvedValueOnce(json(saved)).mockResolvedValueOnce(json({outcome:'saved',recording:saved})).mockResolvedValueOnce(json(saved));vi.stubGlobal('fetch',fetcher);
  expect(await privateRecordingApi.attach(identity,v,team)).toEqual(saved);expect((await privateRecordingApi.resolve(identity,v,team)).recording).toEqual(saved);expect(await privateRecordingApi.read(identity,v,team,id(3))).toEqual(saved);
  expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${id(1)}/private-recordings`,`http://127.0.0.1:8018/workspaces/${id(1)}/private-recordings/resolve`,`http://127.0.0.1:8018/workspaces/${id(1)}/private-recordings/${id(3)}`]);
  for(const [,options] of fetcher.mock.calls){const h=new Headers(options.headers);expect(h.get('X-Cosmas-Private-Recording')).toBe('1');expect(h.get('Authorization')).toBe('Bearer invented-token');expect(h.has('X-Actor-Principal-Id')).toBe(false);expect(options).toMatchObject({credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});}
  expect(identity.getToken).toHaveBeenCalledTimes(3);
});
it.each(['owner','scope','local','workspace','scribe','hash','upstream','extra'])('withholds invalid or cross-bound receipt %s',async fault=>{
  const v=await intent(),r=receipt(v);
  if(fault==='owner')r.owner_id=id(99);if(fault==='scope')r.recovery_scope='a'.repeat(64);if(fault==='local')r.local_recording_id=id(99);if(fault==='workspace')r.workspace_id=id(99);if(fault==='scribe')r.agent_id=id(99);if(fault==='hash')r.attach_sha256='b'.repeat(64);
  const value=fault==='extra'?{...r,audio_uri:'forbidden'}:fault==='upstream'?{...r,audio_uploaded:true}:r;
  await expect(parsePrivateRecordingReceipt(value,v)).rejects.toThrow();
});
it('rejects restored intent tampering or current team change before native credentials',async()=>{
  const v=await intent(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  await expect(privateRecordingApi.attach(identity,{...v,request:{...v.request,local_recording_id:id(99)}},team)).rejects.toThrow();
  await expect(privateRecordingApi.attach(identity,v,{...team,revision:2})).rejects.toThrow();expect(identity.getToken).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it('finish binds exact hash and keeps unknown outcome metadata empty',async()=>{
  const v=await intent(),f=await createPrivateRecordingFinishIntent({idempotency_key:id(4),capture_state:'unknown',manifest_sha256:null,chunks:null,frames:null,ended_at:null}),r={...receipt(v),state:'unknown' as const,finish:{receipt_id:id(5),request_sha256:f.request_sha256,manifest_sha256:null,chunks:null,frames:null,ended_at:null}};
  vi.stubGlobal('fetch',vi.fn(async()=>json(r)));expect(await privateRecordingApi.finish(identity,v,team,id(3),f)).toEqual(r);
  await expect(createPrivateRecordingFinishIntent({...f.request,chunks:1})).rejects.toThrow();
});
it('does not dispatch after late token acquisition exceeds its deadline',async()=>{
  const v=await intent();vi.useFakeTimers();let release!:(v:string)=>void;
  const access={mode:'clerk_jwt' as const,getToken:()=>new Promise<string>(r=>{release=r;})},fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  const result=expect(privateRecordingApi.attach(access,v,team)).rejects.toThrow();
  await vi.waitFor(()=>expect(release).toBeTypeOf('function'));await vi.advanceTimersByTimeAsync(15001);await result;release('late');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
});
