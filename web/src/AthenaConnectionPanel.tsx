import {useEffect,useRef,useState} from 'react';
import {coreConnectionApi} from './core-connection-api';
import type {AthenaCommand,AthenaResult} from './athena-connection-contract';
import {AthenaVisitLinkPanel} from './AthenaVisitLinkPanel';
import {ATHENA_VISIT_LINK_BUILD,type AthenaSourceSelection} from './athena-visit-link-api';
import type {CoreConnection,CoreConnectionCommand} from './core-connection-contract';
import type {AthenaAppointment} from './athena-connection-contract';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {WORKSPACE_AUTHENTICATED_BUILD,WORKSPACE_BUILD,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

export const ATHENA_CONNECTION_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_ATHENA_CONNECTION_ENABLED==='true';
type Window={start_date:string;end_date:string};
export function athenaDateWindow(zone:string):Window{
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const value=(kind:string)=>parts.find(p=>p.type===kind)!.value;
  const start_date=`${value('year')}-${value('month')}-${value('day')}`;
  const end=new Date(start_date+'T00:00:00Z');end.setUTCDate(end.getUTCDate()+6);
  return {start_date,end_date:end.toISOString().slice(0,10)};
}
export function athenaLocalTime(value:string):string{
  // Format the source's calendar components; never convert them to device time.
  return new Intl.DateTimeFormat(undefined,{timeZone:'UTC',dateStyle:'medium',timeStyle:'short'}).format(new Date(value+'Z'));
}
function zoneLabel(zone:string){return new Intl.DateTimeFormat(undefined,{timeZone:zone,timeZoneName:'longGeneric'}).formatToParts(new Date()).find(p=>p.type==='timeZoneName')?.value??zone;}
const statusLabels:Record<string,string>={f:'Booked','2':'Checked in','3':'Checked out','4':'Charge entered',x:'Cancelled'};

export function AthenaConnectionPanel({identity,connectionSha,connection,onBusyChange,onAccessLost,onOpenNotebook,openBlocked=false,visitLinkEnabled=ATHENA_VISIT_LINK_BUILD}:{identity:AuthenticatedWorkspaceIdentity;connectionSha:string;connection?:CoreConnection;onBusyChange?:(busy:boolean)=>void;onAccessLost:(error:unknown)=>void;onOpenNotebook?:(command:CoreConnectionCommand)=>Promise<void>;openBlocked?:boolean;visitLinkEnabled?:boolean}){
  const [snapshot,setSnapshot]=useState<{identity:AuthenticatedWorkspaceIdentity;sha:string;result:AthenaResult;requestWindow?:Window&{offset:number}}|null>(null);
  const [window,setWindow]=useState<Window|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [selected,setSelected]=useState<{source:AthenaAppointment;selection:AthenaSourceSelection}|null>(null),[linkBusy,setLinkBusy]=useState(false);
  const locked=busy||linkBusy;
  const epoch=useRef(0),running=useRef(false),controller=useRef<AbortController|null>(null),scope=useRef({identity,connectionSha});
  scope.current={identity,connectionSha};
  useSetupNavigationBusy(locked,onBusyChange);
  useEffect(()=>{epoch.current++;controller.current?.abort();running.current=false;setSnapshot(null);setSelected(null);setLinkBusy(false);setWindow(null);setError('');setBusy(false);return()=>{epoch.current++;controller.current?.abort();running.current=false;};},[identity,connectionSha]);
  const result=snapshot?.identity===identity&&snapshot.sha===connectionSha?snapshot.result:null;
  const discovery=result?.athena_discovery,account=discovery?.account;
  const page=discovery?.action==='appointments'&&snapshot?.requestWindow?.start_date===window?.start_date&&snapshot?.requestWindow?.end_date===window?.end_date?discovery:null;
  async function run(command:AthenaCommand){
    if(running.current||linkBusy)return;
    running.current=true;
    const current=++epoch.current;controller.current?.abort();const abort=new AbortController();controller.current=abort;
    const isCurrent=()=>current===epoch.current&&scope.current.identity===identity&&scope.current.connectionSha===connectionSha;
    setBusy(true);setError('');setSnapshot(null);setSelected(null);
    try{
      const received=await coreConnectionApi.read(identity,command,abort.signal);
      if(!isCurrent())return;
      setSnapshot({identity,sha:connectionSha,result:received,...(command.action==='athena_appointments'?{requestWindow:{start_date:command.start_date,end_date:command.end_date,offset:command.offset}}:{})});
      if(command.action==='athena_connection')setWindow(received.athena_discovery.account?athenaDateWindow(received.athena_discovery.account.department_timezone):null);
    }catch(cause){
      if(!isCurrent())return;
      setSnapshot(null);
      if(cause instanceof WorkspaceApiError&&[401,403,409].includes(cause.status)){onAccessLost(cause);return;}
      setError(cause instanceof WorkspaceApiError&&cause.status===404?'Athena is not enabled for your practice yet. Ask your practice administrator to complete the connection.':'Athena could not be checked. Check the connection again to retry.');
    }finally{if(isCurrent()){running.current=false;setBusy(false);}}
  }
  function appointments(offset=0){
    if(!account||!window)return;
    const difference=Date.parse(window.end_date)-Date.parse(window.start_date);
    if(!Number.isFinite(difference)||difference<0||difference>=31*86400000){setError('Choose a date range of up to 31 days.');return;}
    void run({action:'athena_appointments',request_nonce:crypto.randomUUID(),connection_sha256:connectionSha,account_sha256:account.account_sha256,...window,offset});
  }
  function changeWindow(next:Window){
    setWindow(next);setSelected(null);setError('');
  }
  return <section className="athena-connection-setup" aria-label="Athena connection">
    <h3>Athena appointments</h3>
    <p>Read-only connection. View the Athena schedule enabled by your practice. CosmasOS cannot change appointments or records in Athena.</p>
    {error&&<p role="alert">{error}</p>}
    <button disabled={locked} onClick={()=>void run({action:'athena_connection',request_nonce:crypto.randomUUID(),connection_sha256:connectionSha})}>{busy?'Checking Athena…':'Check Athena connection'}</button>
    {discovery&&!account&&<p role="status">Your practice has not connected an Athena schedule for this account yet. Ask your practice administrator to finish setup.</p>}
    {account&&window&&<>
      <p role="status">{page?'Schedule read successfully.':'Your practice has enabled this schedule. Check appointments to verify access.'}</p>
      <h4>{account.department_label}</h4>
      <p className="team-fine">Times are shown in {zoneLabel(account.department_timezone)}.</p>
      {account.environment==='preview'&&<p className="team-fine">Athena Preview environment</p>}
      <div className="connection-date-range"><label>From<input type="date" value={window.start_date} disabled={locked} onChange={e=>changeWindow({...window,start_date:e.target.value})}/></label>
        <label>Through<input type="date" value={window.end_date} disabled={locked} onChange={e=>changeWindow({...window,end_date:e.target.value})}/></label></div>
      <p className="team-fine">Up to 31 days, including both dates.</p>
      <button disabled={locked} onClick={()=>appointments()}>View Athena appointments</button>
      {page&&<>
        <p className="team-fine">Patient names are not available from this connection yet. View patient details in Athena.</p>
        <ul className="connection-appointments">{page.appointments.map(row=><li key={row.appointment_ref}>
          <strong>{athenaLocalTime(row.source_local_start)}</strong>
          <span>{statusLabels[row.source_status]} · {row.duration_minutes} minutes</span>
          {visitLinkEnabled&&connection&&<button disabled={locked} onClick={()=>setSelected({source:row,selection:{...snapshot!.requestWindow!,appointment_ref:row.appointment_ref,source_sha256:row.source_sha256}})}>Connect or open visit</button>}
        </li>)}</ul>
        {!page.appointments.length&&<p>No appointments returned for this date range.</p>}
        {page.next_offset!==null&&<button disabled={locked} onClick={()=>appointments(page.next_offset!)}>Next Athena appointments</button>}
        {page.truncated&&<p role="status">There are more appointments than this view can show. Choose a shorter date range.</p>}
        <p className="team-fine">Refresh to see recent schedule changes.</p>
      </>}
    </>}
    {visitLinkEnabled&&connection&&account&&page&&selected&&<AthenaVisitLinkPanel identity={identity} connection={connection} account={account} source={selected.source} selection={selected.selection} onBusyChange={setLinkBusy} onAccessLost={onAccessLost} onOpenNotebook={onOpenNotebook} openBlocked={openBlocked} onClose={()=>setSelected(null)}/>}
  </section>;
}
