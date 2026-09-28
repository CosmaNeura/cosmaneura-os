import {useEffect,useRef,useState} from 'react';
import {coreConnectionApi} from './core-connection-api';
import type {AppointmentSetupCommand,AppointmentSetupResult} from './core-appointment-setup-contract';
import {isCoreWindow,type CoreCursor,type CoreWindow} from './core-connection-contract';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {WORKSPACE_AUTHENTICATED_BUILD,WORKSPACE_BUILD,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

export const CORE_APPOINTMENT_SETUP_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_CORE_APPOINTMENT_SETUP_ENABLED==='true';
type Snapshot={scope:string;identity:AuthenticatedWorkspaceIdentity;result:AppointmentSetupResult;cursor?:CoreCursor};
export function CoreAppointmentSetupPanel({identity,connectionSha,window,onBusyChange,onAccessLost,onConnected}:{identity:AuthenticatedWorkspaceIdentity;connectionSha:string;window:CoreWindow;onBusyChange?:(busy:boolean)=>void;onAccessLost:(error:unknown)=>void;onConnected:()=>void}){
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const scope=JSON.stringify([connectionSha,window.start_date,window.end_date]);
  const currentScope=useRef({identity,scope});currentScope.current={identity,scope};
  const epoch=useRef(0),running=useRef(false),controller=useRef<AbortController|null>(null);
  useSetupNavigationBusy(busy,onBusyChange);
  useEffect(()=>{epoch.current++;controller.current?.abort();running.current=false;setSnapshot(null);setError('');setBusy(false);return()=>{epoch.current++;controller.current?.abort();running.current=false;};},[identity,scope]);
  const result=snapshot?.identity===identity&&snapshot.scope===scope?snapshot.result.appointment_setup:null;
  async function run(action:AppointmentSetupCommand['action'],cursor?:CoreCursor){
    if(running.current)return;
    if(!isCoreWindow(window)){setError('Choose a date range of 1 to 31 days, with the end date after the start date.');return;}
    if(action==='appointment_setup_connect'&&(!result||result.action!=='preview'||!result.eligible_count))return;
    running.current=true;const version=++epoch.current;controller.current?.abort();const abort=new AbortController();controller.current=abort;
    const isCurrent=()=>version===epoch.current&&currentScope.current.identity===identity&&currentScope.current.scope===scope;
    const command:AppointmentSetupCommand={action,request_nonce:crypto.randomUUID(),connection_sha256:connectionSha,window,...(cursor?{cursor}:{}),...(action==='appointment_setup_connect'?{plan_sha256:result!.plan_sha256}:{})};
    setBusy(true);setError('');setSnapshot(null);
    try{
      const received=await coreConnectionApi.read(identity,command,abort.signal);
      if(!isCurrent())return;
      setSnapshot({identity,scope,result:received,cursor});
      if(action==='appointment_setup_connect')onConnected();
    }catch(cause){
      if(!isCurrent())return;
      if(cause instanceof WorkspaceApiError&&[401,403,409].includes(cause.status)){onAccessLost(cause);return;}
      setError(cause instanceof WorkspaceApiError&&cause.status===404?'Appointment setup is not enabled for your practice yet.':action==='appointment_setup_connect'?'The connection result could not be verified. It may have been saved. View appointments or check again before confirming.':'Existing appointments could not be checked. Try again.');
    }finally{if(isCurrent()){running.current=false;setBusy(false);}}
  }
  return <section className="core-appointment-setup" aria-label="Connect existing appointments">
    <h4>Missing existing appointments?</h4>
    <p>Check your practice appointments in the selected date range and connect those available to your account.</p>
    {error&&<p role="alert">{error}</p>}
    <button disabled={busy} onClick={()=>void run('appointment_setup_preview')}>{busy?'Checking appointments…':'Check existing appointments'}</button>
    {result&&<>
      {result.action==='connect'?<p role="status">{result.connected_now_count} appointments connected. Choose View appointments to open a notebook.</p>:<p role="status">{result.eligible_count} ready to connect · {result.already_connected_count} already connected · {result.review_required_count} need practice review</p>}
      {result.review_required_count>0&&<p>Ask your practice administrator to review the remaining connections.</p>}
      {result.action==='preview'&&result.eligible_count>0&&<button className="team-primary" disabled={busy} onClick={()=>void run('appointment_setup_connect',snapshot?.cursor)}>Connect existing appointments</button>}
      {result.next_cursor&&<button disabled={busy} onClick={()=>void run('appointment_setup_preview',result.next_cursor!)}>Check next appointments</button>}
      {!result.scanned_count&&<p>No existing appointments found in this part of the date range.</p>}
      <p className="team-fine">Checked {result.scanned_count} appointments on this page.</p>
    </>}
  </section>;
}
