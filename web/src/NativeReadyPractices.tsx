import {useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {AppleHostedStatus} from './AppleHostedStatus';
import type {EnrollmentApi,EnrollmentIdentity} from './enrollment-api';
import {EnrollmentError,type EnrollmentPractices,type EnrollmentStatus} from './enrollment-contract';
import './native-ready-practices.css';

type SavedPractices={status:EnrollmentStatus;memberships:EnrollmentPractices};
type Owner={active:boolean;pending:boolean;controller:AbortController|null};

/** Discovery uses server membership. Only the native host can admit a workspace. */
export function NativeReadyPractices({api,identity,onOpenCurrent,onCreatePractice,onPendingChange,accountControls}:{
  api:EnrollmentApi;identity:EnrollmentIdentity;onOpenCurrent:()=>Promise<void>;onCreatePractice:()=>void;
  onPendingChange:(pending:boolean)=>void;accountControls:ReactNode;
}) {
  const owner=useRef<Owner|null>(null);
  const [saved,setSaved]=useState<SavedPractices|null>(null),[busy,setBusy]=useState(true),[failed,setFailed]=useState<string|null>(null);
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
      setSaved(null);setFailed(error instanceof EnrollmentError&&error.code==='practice_selection_changed'
        ?'Your current practice changed. Check your practices before opening Chief.'
        :'Your practices could not be checked. Try again, or return to your existing workspace.');
    }}
    finally{if(owner.current===captured&&captured.active){captured.pending=false;captured.controller=null;onPendingChange(false);setBusy(false);}}
  }
  function refresh(){void run(async signal=>{const next=await read(signal);if(current())setSaved(next);});}
  useLayoutEffect(()=>{
    const captured:Owner={active:true,pending:false,controller:null};owner.current=captured;
    setSaved(null);setFailed(null);refresh();
    return()=>{captured.active=false;captured.controller?.abort();if(owner.current===captured)owner.current=null;onPendingChange(false);};
  },[api,identity,onPendingChange]);
  const ready=saved?.memberships.practices.filter(practice=>practice.workspace_status==='ready')??[];
  const selected=ready.find(practice=>practice.id===saved?.memberships.active_practice_id);
  const canOpen=Boolean(selected&&saved?.status.stage==='ready'&&saved.status.workspace.status==='ready');
  const needsSetup=Boolean(saved&&saved.status.stage!=='ready');
  function open(){
    if(!canOpen||!saved)return;const expected=saved;
    void run(async signal=>{
      const fresh=await read(signal);
      if(fresh.status.practice?.id!==expected.status.practice?.id||fresh.status.stage!=='ready'||fresh.status.workspace.status!=='ready'||
        fresh.status.workspace.organization_id!==expected.status.workspace.organization_id||fresh.status.workspace.box_id!==expected.status.workspace.box_id)
        throw new EnrollmentError(409,'practice_selection_changed');
      if(!fresh.memberships.practices.some(practice=>practice.id===fresh.memberships.active_practice_id&&practice.workspace_status==='ready'))
        throw new EnrollmentError(409,'practice_selection_changed');
      // This existing host action opens its freshly verified current practice.
      // Named switching needs a host-owned expected-practice/revision binding;
      // a renderer-only dropdown must never imply that it supplies that fence.
      await onOpenCurrent();
    });
  }
  return <div className="native-practices-entry"><AppleHostedStatus title="Your practices" detail="Ready practices are listed below. Open Chief to continue in your current signed-in practice." role="status">
    <div className="native-ready-practices">
      {busy&&<p role="status">Checking your practices…</p>}
      {failed&&<p role="alert">{failed}</p>}
      {saved&&<>{ready.length?<ul aria-label="Ready practices">{ready.map(practice=><li key={practice.id}>
        <strong>{practice.display_name}</strong>{practice.id===saved.memberships.active_practice_id&&<span>Current practice</span>}
      </li>)}</ul>:<p>No ready practice is connected to this signed-in account yet.</p>}
        {ready.length>0&&!canOpen&&<p>Your current practice is still being set up. You can return to your existing workspace.</p>}
        {canOpen&&<button className="button" disabled={busy} onClick={open}>Open Chief</button>}</>}
      <button className="button secondary" disabled={busy} onClick={refresh}>Check practices</button>
      {needsSetup&&<button className="button secondary" disabled={busy} onClick={()=>{if(current()&&!owner.current?.pending)onCreatePractice();}}>
        {saved?.status.practice?'Continue practice setup':'Create a new practice'}</button>}
      {accountControls}
    </div>
  </AppleHostedStatus></div>;
}
