import {createPrivateRecordingIntent,createPrivateRecordingFinishIntent,validatePrivateRecordingIntent,
  parsePrivateRecordingReceipt,privateRecordingApi,type PrivateRecordingIntent,type PrivateRecordingReceipt,type PrivateRecordingFinishIntent} from './private-recording-api';
import type {PrivateRecordingRuntime,PrivateRecordingStore} from './private-recording-runtime';
import type {AuthenticatedWorkspaceIdentity,ProviderTeam,Workspace} from './workspace-api';
import {WorkspaceApiError} from './workspace-api';
type Snapshot=Awaited<ReturnType<PrivateRecordingRuntime['snapshotForLedger']>>;
export type PrivateRecordingLedger={contract:'cosmas.private-recording.ledger.v1';recording_id:string;workspace_id:string;
  recovery_scope:string;attach:PrivateRecordingIntent;receipt:PrivateRecordingReceipt|null;finish:PrivateRecordingFinishIntent|null;
  state:'attach_pending'|'attached'|'finish_pending'|'finished';uncertain:boolean;retry_ready:boolean};
type Options={identity:AuthenticatedWorkspaceIdentity;team:ProviderTeam;workspace:Workspace;store:PrivateRecordingStore;scope:string;isCurrent:()=>boolean};
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
function need(v:unknown):asserts v {if(!v)throw new WorkspaceApiError(503,'private_recording_unavailable');}

/** Encrypted exact-request custody. This class neither starts the mic nor uploads audio. */
export class PrivateRecordingLedgerController {
  private busy=false;
  constructor(private options:Options){}
  private current(){need(this.options.isCurrent());}
  private async wait<T>(promise:Promise<T>):Promise<T>{this.current();const value=await promise;this.current();return value;}
  private key(id:string){need(/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id));return 'ledger:'+id;}
  private async validate(value:unknown,id:string):Promise<PrivateRecordingLedger>{
    need(closed(value,'contract,recording_id,workspace_id,recovery_scope,attach,receipt,finish,state,uncertain,retry_ready')&&value.contract==='cosmas.private-recording.ledger.v1'&&value.recording_id===id&&value.workspace_id===this.options.workspace.id&&value.recovery_scope===this.options.team.recovery_scope&&typeof value.uncertain==='boolean'&&typeof value.retry_ready==='boolean'&&['attach_pending','attached','finish_pending','finished'].includes(String(value.state)));
    const record=value as PrivateRecordingLedger;await this.wait(validatePrivateRecordingIntent(record.attach,this.options.team));
    need(record.attach.workspace_id===record.workspace_id&&record.attach.request.local_recording_id===id);
    if(record.receipt!==null)await this.wait(parsePrivateRecordingReceipt(record.receipt,record.attach));
    if(record.state==='attach_pending')need(record.receipt===null&&record.finish===null);
    else need(record.receipt!==null);
    if(record.finish!==null){const actual=await this.wait(createPrivateRecordingFinishIntent(record.finish.request));need(actual.request_sha256===record.finish.request_sha256);}
    if(record.state==='finish_pending'||record.state==='finished')need(record.finish!==null);
    else need(record.finish===null);
    if(record.state==='finished')need(record.receipt?.finish?.request_sha256===record.finish?.request_sha256);
    return record;
  }
  async readCurrent(id:string):Promise<PrivateRecordingLedger|null>{
    const saved=await this.wait(this.options.store.read(this.key(id)));return saved===null?null:this.validate(saved,id);
  }
  private async persist(id:string,before:PrivateRecordingLedger|null,next:PrivateRecordingLedger){
    await this.wait(this.options.store.write(this.key(id),before,next));return next;
  }
  private async exclusive<T>(action:()=>Promise<T>){need(!this.busy);this.busy=true;try{this.current();return await action();}finally{this.busy=false;}}
  private async dispatch(record:PrivateRecordingLedger):Promise<PrivateRecordingLedger>{
    const marked={...record,uncertain:true,retry_ready:false};
    await this.persist(record.recording_id,record,marked);
    // Any failure, including local receipt persistence, leaves the exact request for GET/resolve.
    const receipt=record.state==='attach_pending'
      ? await this.wait(privateRecordingApi.attach(this.options.identity,record.attach,this.options.team))
      : await this.wait(privateRecordingApi.finish(this.options.identity,record.attach,this.options.team,record.receipt!.recording_id,record.finish!));
    const settled={...marked,receipt,state:(record.state==='attach_pending'?'attached':'finished') as PrivateRecordingLedger['state'],uncertain:false};
    return this.persist(record.recording_id,marked,settled);
  }
  attach(snapshot:Snapshot):Promise<PrivateRecordingLedger>{return this.exclusive(async()=>{
    need(snapshot.scope===this.options.scope&&snapshot.startedAt!==null);
    const prior=await this.readCurrent(snapshot.recordingId);
    if(prior){need(prior.state!=='attach_pending');return prior;}
    const {language:_,...consent}=snapshot.consent;
    const attach=await this.wait(createPrivateRecordingIntent(this.options.team,this.options.workspace,snapshot.recordingId,consent,snapshot.startedAt));
    const record:PrivateRecordingLedger={contract:'cosmas.private-recording.ledger.v1',recording_id:snapshot.recordingId,workspace_id:this.options.workspace.id,recovery_scope:attach.recovery_scope,attach,receipt:null,finish:null,state:'attach_pending',uncertain:true,retry_ready:false};
    await this.persist(snapshot.recordingId,null,record);return this.dispatch(record);
  });}
  finish(snapshot:Snapshot):Promise<PrivateRecordingLedger>{return this.exclusive(async()=>{
    need(snapshot.scope===this.options.scope&&['sealed','interrupted'].includes(snapshot.phase)&&snapshot.chunks>0&&snapshot.frames>0);
    const prior=await this.readCurrent(snapshot.recordingId);need(prior&&prior.receipt);
    if(prior.state==='finished')return prior;need(prior.state==='attached');
    const finish=await this.wait(createPrivateRecordingFinishIntent({idempotency_key:crypto.randomUUID(),capture_state:snapshot.phase==='sealed'?'finished':'interrupted',manifest_sha256:snapshot.manifestSHA256,chunks:snapshot.chunks,frames:snapshot.frames,ended_at:snapshot.updatedAt}));
    const pending={...prior,finish,state:'finish_pending' as const,uncertain:true,retry_ready:false};
    await this.persist(snapshot.recordingId,prior,pending);return this.dispatch(pending);
  });}
  checkSaved(id:string):Promise<PrivateRecordingLedger>{return this.exclusive(async()=>{
    const prior=await this.readCurrent(id);need(prior);
    if(prior.state==='attach_pending'){
      const result=await this.wait(privateRecordingApi.resolve(this.options.identity,prior.attach,this.options.team));
      const next=result.outcome==='not_found'?{...prior,retry_ready:true,uncertain:true}
        :{...prior,receipt:result.recording,state:'attached' as const,uncertain:false,retry_ready:false};
      return this.persist(id,prior,next);
    }
    need(prior.receipt);const receipt=await this.wait(privateRecordingApi.read(this.options.identity,prior.attach,this.options.team,prior.receipt.recording_id));
    if(prior.state==='finish_pending'){
      need(prior.finish);const found=receipt.finish?.request_sha256===prior.finish.request_sha256;
      need(found||receipt.finish===null);
      return this.persist(id,prior,{...prior,receipt,state:found?'finished':'finish_pending',uncertain:!found,retry_ready:!found});
    }
    return this.persist(id,prior,{...prior,receipt,uncertain:false,retry_ready:false});
  });}
  retryExact(id:string):Promise<PrivateRecordingLedger>{return this.exclusive(async()=>{
    const record=await this.readCurrent(id);need(record?.retry_ready&&['attach_pending','finish_pending'].includes(record.state));
    return this.dispatch(record);
  });}
}
