import {useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {AppleHostedStatus} from './AppleHostedStatus';
import type {EnrollmentApi,EnrollmentIdentity} from './enrollment-api';
import {EnrollmentError,type EnrollmentPractices,type EnrollmentStatus} from './enrollment-contract';
import './native-ready-practices.css';
import {hasUnsavedWork,useUnsavedWorkPresent} from './unsaved-work';

type SavedPractices={status:EnrollmentStatus;memberships:EnrollmentPractices};
type Selection={id:string;originalId:string|null;revision:number;key:string};
type Owner={active:boolean;pending:boolean;controller:AbortController|null;selection:Selection|null};

/** Discovery uses server membership. Only the native host can admit a workspace. */
export function NativeReadyPractices({api,identity,onOpenCurrent,onOpenSelected,onCreatePractice,onPendingChange,accountControls}:{
  api:EnrollmentApi;identity:EnrollmentIdentity;onOpenCurrent:()=>Promise<void>;onCreatePractice:()=>void;
  onOpenSelected?:(status:EnrollmentStatus)=>Promise<void>;
  onPendingChange:(pending:boolean)=>void;accountControls:ReactNode;
}) {
  const owner=useRef<Owner|null>(null);
  const [saved,setSaved]=useState<SavedPractices|null>(null),[busy,setBusy]=useState(true),[failed,setFailed]=useState<string|null>(null);
  const [chosen,setChosen]=useState(''),[uncertain,setUncertain]=useState(false),[checkedPending,setCheckedPending]=useState(false);
  const workPending=useUnsavedWorkPresent();
  const current=()=>Boolean(owner.current?.active&&identity.isCurrent());
  async function read(signal:AbortSignal):Promise<SavedPractices>{
    const status=await api.status(identity,signal),memberships=await api.practices(identity,signal);
    if(!current()||signal.aborted)throw new EnrollmentError(401);
    if(memberships.active_practice_id!==(status.practice?.id??null))throw new EnrollmentError(409,'practice_selection_changed');
    return {status,memberships};
  }
  async function run(action:(signal:AbortSignal)=>Promise<void>){
    const captured=owner.current;if(!captured?.active||captured.pending||!identity.isCurrent())return;
    captured.pending=true;captured.controller=new AbortController();onPendingChange(true);setBusy(true);setFailed(null);
    try{await action(captured.controller.signal);}
    catch(error){if(owner.current===captured&&captured.active&&identity.isCurrent()){
      setSaved(null);
      if(captured.selection&&!(error instanceof EnrollmentError&&[401,403,409,422].includes(error.status))){
        setUncertain(true);setCheckedPending(false);setFailed('Your practice choice may be saved. Check the saved choice before retrying.');
      }else{captured.selection=null;setUncertain(false);setFailed(error instanceof EnrollmentError&&error.code==='practice_selection_changed'
          ?'Your current practice changed. Check your practices before opening Chief.'
          :'Your practices could not be checked. Try again, or return to your existing workspace.');}
    }}
    finally{if(owner.current===captured&&captured.active){captured.pending=false;captured.controller=null;onPendingChange(captured.selection!==null);setBusy(false);}}
  }
  function refresh(){void run(async signal=>{
    const next=await read(signal),pending=owner.current?.selection;
    if(pending){
      // Registry revisions combine account and selected-practice counters, so
      // a saved switch can have an equal or lower total. Fresh target binding
      // resolves the choice; opening still requires a separate explicit action.
      if(next.memberships.active_practice_id===pending.id&&next.status.practice?.id===pending.id&&next.status.stage==='ready'&&
        next.status.workspace.status==='ready'&&next.memberships.practices.some(practice=>practice.id===pending.id&&practice.workspace_status==='ready')){
        owner.current!.selection=null;setUncertain(false);setCheckedPending(false);setChosen(pending.id);
      }else if(next.memberships.active_practice_id===pending.originalId&&(next.status.practice?.id??null)===pending.originalId&&
        next.status.revision===pending.revision){setCheckedPending(true);setUncertain(true);}
      else{owner.current!.selection=null;setUncertain(false);setCheckedPending(false);setChosen(next.memberships.active_practice_id??'');
        setFailed('Your current practice changed. Choose a practice again before opening Chief.');}
    }else setChosen(next.memberships.active_practice_id??'');
    if(current())setSaved(next);
  });}
  useLayoutEffect(()=>{
    const captured:Owner={active:true,pending:false,controller:null,selection:null};owner.current=captured;
    setSaved(null);setFailed(null);setUncertain(false);setCheckedPending(false);setChosen('');refresh();
    return()=>{captured.active=false;captured.controller?.abort();if(owner.current===captured)owner.current=null;onPendingChange(false);};
  },[api,identity,onPendingChange]);
  const ready=saved?.memberships.practices.filter(practice=>practice.workspace_status==='ready')??[];
  const selected=ready.find(practice=>practice.id===saved?.memberships.active_practice_id);
  const canOpen=Boolean(selected&&saved?.status.stage==='ready'&&saved.status.workspace.status==='ready');
  const needsSetup=Boolean(saved&&saved.status.stage!=='ready');
  async function applySelection(selection:Selection,signal:AbortSignal){
    const result=await api.selectPractice(identity,{expected_revision:selection.revision,practice_id:selection.id},selection.key,signal);
    const next=await read(signal);
    if(result.practice?.id!==selection.id||result.stage!=='ready'||next.memberships.active_practice_id!==selection.id||next.status.stage!=='ready'||
      next.status.revision<result.revision||next.status.workspace.organization_id!==result.workspace.organization_id||next.status.workspace.box_id!==result.workspace.box_id)
      throw new EnrollmentError(409,'practice_selection_changed');
    owner.current!.selection=null;setUncertain(false);setCheckedPending(false);setSaved(next);setChosen(selection.id);
    await onOpenSelected!(next.status);
  }
  function open(){
    if(!saved||uncertain||hasUnsavedWork()||!current()||owner.current?.pending||owner.current?.selection)return;const expected=saved;
    if(onOpenSelected){
      if(!ready.some(practice=>practice.id===chosen))return;
      if(chosen!==saved.memberships.active_practice_id){
        const selection={id:chosen,originalId:saved.memberships.active_practice_id,revision:saved.status.revision,key:crypto.randomUUID()};owner.current!.selection=selection;
        void run(signal=>applySelection(selection,signal));return;
      }
    }else if(!canOpen)return;
    void run(async signal=>{
      const fresh=await read(signal);
      if(fresh.status.practice?.id!==expected.status.practice?.id||fresh.status.stage!=='ready'||fresh.status.workspace.status!=='ready'||
        fresh.status.workspace.organization_id!==expected.status.workspace.organization_id||fresh.status.workspace.box_id!==expected.status.workspace.box_id)
        throw new EnrollmentError(409,'practice_selection_changed');
      if(!fresh.memberships.practices.some(practice=>practice.id===fresh.memberships.active_practice_id&&practice.workspace_status==='ready'))
        throw new EnrollmentError(409,'practice_selection_changed');
      // New hosts bind the exact practice/revision before native installation.
      // Older hosts retain current-practice discovery and their existing action.
      if(onOpenSelected)await onOpenSelected(fresh.status);else await onOpenCurrent();
    });
  }
  return <div className="native-practices-entry"><AppleHostedStatus title="Your practices" detail="Ready practices are listed below. Open Chief to continue in your current signed-in practice." role="status">
    <div className="native-ready-practices">
      {busy&&<p role="status">Checking your practices…</p>}
      {failed&&<p role="alert">{failed}</p>}
      {saved&&<>{ready.length?<ul aria-label="Ready practices">{ready.map(practice=><li key={practice.id}>
        {onOpenSelected?<button className="button secondary" aria-pressed={chosen===practice.id} disabled={busy||uncertain||workPending}
          onClick={()=>{if(current()&&!owner.current?.pending&&!owner.current?.selection&&!hasUnsavedWork())setChosen(practice.id);}}>{practice.display_name}</button>:<strong>{practice.display_name}</strong>}
        {practice.id===saved.memberships.active_practice_id&&<span>Current practice</span>}
      </li>)}</ul>:<p>No ready practice is connected to this signed-in account yet.</p>}
        {ready.length>0&&!canOpen&&<p>Your current practice is still being set up. You can return to your existing workspace.</p>}
        {(canOpen||onOpenSelected&&ready.some(practice=>practice.id===chosen))&&<button className="button" disabled={busy||uncertain||workPending} onClick={open}>
          {onOpenSelected&&chosen!==saved.memberships.active_practice_id?'Open selected practice':'Open Chief'}</button>}</>}
      <button className="button secondary" disabled={busy} onClick={refresh}>{uncertain?'Check saved choice':'Check practices'}</button>
      {uncertain&&checkedPending&&<button className="button secondary" disabled={busy||workPending} onClick={()=>{
        const selection=owner.current?.selection;if(selection&&!hasUnsavedWork())void run(signal=>applySelection(selection,signal));
      }}>Retry saved choice</button>}
      {needsSetup&&<button className="button secondary" disabled={busy||uncertain||workPending} onClick={()=>{if(current()&&!owner.current?.pending&&!owner.current?.selection&&!hasUnsavedWork())onCreatePractice();}}>
        {saved?.status.practice?'Continue practice setup':'Create a new practice'}</button>}
      {accountControls}
    </div>
  </AppleHostedStatus></div>;
}
