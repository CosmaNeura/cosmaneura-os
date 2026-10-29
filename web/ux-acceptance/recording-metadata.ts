import type {PrivateRecordingAttach,PrivateRecordingFinish,PrivateRecordingReceipt} from '../src/private-recording-api';
import {modelCanonical} from '../src/model-work-request';
import {modelUuid} from '../src/model-work-test-fixture';
import type {ProviderTeam,Workspace} from '../src/workspace-api';

/** In-tab metadata server for invented recordings. Audio stays in the actual
 * encrypted queue; this fixture never receives audio or calls a service. */
export function recordingMetadata(ownerId:string,team:()=>ProviderTeam,workspace:()=>Workspace){
  const receipts=new Map<string,PrivateRecordingReceipt>(),commands=new Map<string,unknown>();
  const hash=async(kind:string,request:unknown)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(modelCanonical({contract:`cosmas.private-recording.${kind}.v1`,request})))),b=>b.toString(16).padStart(2,'0')).join('');
  const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  return async(path:string,init?:RequestInit):Promise<Response|null>=>{
    const route=/^\/workspaces\/([a-f0-9-]{36})\/private-recordings(?:\/(resolve|[a-f0-9-]{36}))?(?:\/(finish))?$/.exec(path);
    if(!route)return null;
    const current=workspace();if(route[1]!==current.id)throw new Error('Unknown invented recording workspace');
    if(init?.method==='GET')return json(receipts.get(route[2])??null);
    if(init?.method!=='POST'||typeof init.body!=='string')throw new Error('Unsupported invented recording operation');
    const body=JSON.parse(init.body) as PrivateRecordingAttach|PrivateRecordingFinish;
    const key=path+':'+body.idempotency_key;if(commands.has(key))return json(commands.get(key));
    if(route[2]==='resolve'){
      const bodyHash=await hash('attach',body),recording=[...receipts.values()].find(row=>row.attach_sha256===bodyHash)??null;
      return json({outcome:recording?'saved':'not_found',recording});
    }
    let result:PrivateRecordingReceipt;
    if(route[3]==='finish'){
      const prior=receipts.get(route[2]),finish=body as PrivateRecordingFinish;if(!prior)throw new Error('Unknown invented recording');
      result={...prior,state:finish.capture_state,finish:{receipt_id:crypto.randomUUID(),request_sha256:await hash('finish',finish),manifest_sha256:finish.manifest_sha256,chunks:finish.chunks,frames:finish.frames,ended_at:finish.ended_at}};
    }else{
      const attach=body as PrivateRecordingAttach,config=team();
      if(attach.consent?.all_parties_consented!==true||attach.expected_workspace_revision!==current.revision||attach.bot.team_revision!==config.revision)throw new Error('Invented recording consent or version does not match');
      result={contract:'cosmas.private-recording.v1',custody:'local_device_metadata',recording_id:crypto.randomUUID(),local_recording_id:attach.local_recording_id,workspace_id:current.id,workspace_revision:current.revision,owner_id:ownerId,box_id:modelUuid(9000),agent_id:modelUuid(101),team_revision_id:modelUuid(9001),recovery_scope:config.recovery_scope!,attach_sha256:await hash('attach',attach),started_at:attach.started_at,created_at:new Date().toISOString(),state:'unfinished',finish:null,link:null,upstream_capture_admitted:false,audio_uploaded:false,transcription_started:false};
    }
    receipts.set(result.recording_id,result);commands.set(key,structuredClone(result));return json(result);
  };
}
