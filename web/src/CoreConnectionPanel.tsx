import {useEffect,useRef,useState} from 'react';
import {coreConnectionApi} from './core-connection-api';
import {CoreAppointmentSetupPanel,CORE_APPOINTMENT_SETUP_BUILD} from './CoreAppointmentSetupPanel';
import {AthenaConnectionPanel,ATHENA_CONNECTION_BUILD} from './AthenaConnectionPanel';
import type {CoreConnectionCommand,CoreConnectionResult,CoreCursor,CoreWindow} from './core-connection-contract';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {WORKSPACE_AUTHENTICATED_BUILD,WORKSPACE_BUILD,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

export const CORE_CONNECTION_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_CORE_CONNECTION_ENABLED==='true';
export const CONNECTION_ONBOARDING_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_CONNECTION_ONBOARDING_ENABLED==='true';
function initialWindow():CoreWindow{
  const today=new Date();const start_date=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  const end=new Date(start_date+'T00:00:00Z');end.setUTCDate(end.getUTCDate()+7);
  return {start_date,end_date:end.toISOString().slice(0,10)};
}

export function CoreConnectionPanel({identity,onBusyChange,onAuthenticationLost,onOpenNotebook,openBlocked=false,athenaEnabled=ATHENA_CONNECTION_BUILD,appointmentSetupEnabled=CORE_APPOINTMENT_SETUP_BUILD}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onOpenNotebook?:(command:CoreConnectionCommand)=>Promise<void>;openBlocked?:boolean;athenaEnabled?:boolean;appointmentSetupEnabled?:boolean;onAuthenticationLost:(error:unknown)=>void}){
  const [storedConnection,storeConnection]=useState<{identity:AuthenticatedWorkspaceIdentity;value:CoreConnectionResult}|null>(null),[storedPage,storePage]=useState<{identity:AuthenticatedWorkspaceIdentity;value:CoreConnectionResult}|null>(null);
  const connection=storedConnection?.identity===identity?storedConnection.value:null,page=storedPage?.identity===identity?storedPage.value:null;
  const setConnection=(value:CoreConnectionResult|null)=>storeConnection(value?{identity,value}:null),setPage=(value:CoreConnectionResult|null)=>storePage(value?{identity,value}:null);
  const currentIdentity=useRef(identity);currentIdentity.current=identity;
  const [window,setWindow]=useState(initialWindow),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [athenaBusy,setAthenaBusy]=useState(false),[setupBusy,setSetupBusy]=useState(false);
  const epoch=useRef(0),controller=useRef<AbortController|null>(null);
  useSetupNavigationBusy(busy||athenaBusy||setupBusy,onBusyChange);
  useEffect(()=>{epoch.current++;controller.current?.abort();setConnection(null);setPage(null);setError('');setBusy(false);return()=>{epoch.current++;controller.current?.abort();};},[identity]);
  async function run(command:Omit<CoreConnectionCommand,'request_nonce'>){
    if(busy||athenaBusy||setupBusy)return;
    const current=++epoch.current;controller.current?.abort();const abort=new AbortController();controller.current=abort;
    setBusy(true);setError('');setPage(null);
    try{
      const result=await coreConnectionApi.read(identity,{...command,request_nonce:crypto.randomUUID()},abort.signal);
      if(current!==epoch.current||currentIdentity.current!==identity)return;
      setConnection(result);if(command.action==='encounters')setPage(result);
    }catch(cause){
      if(current!==epoch.current||currentIdentity.current!==identity)return;
      setConnection(null);setPage(null);
      if(cause instanceof WorkspaceApiError&&cause.status===401){setError('Sign in again to check your connection.');onAuthenticationLost(cause);}
      else if(cause instanceof WorkspaceApiError&&cause.status===403)setError('Your practice connection needs review. Ask your practice administrator to confirm access for this account.');
      else if(cause instanceof WorkspaceApiError&&cause.status===404)setError('Cosmaneura connection setup is not enabled for this practice yet.');
      else if(cause instanceof WorkspaceApiError&&cause.status===409)setError('The connection changed or needs practice review. Check its current status before continuing.');
      else setError(command.action==='connect'?'The confirmation could not be verified. It may have been saved; check connection status before confirming again.':'The connection could not be checked. Your saved work is unchanged. Try again.');
    }finally{if(current===epoch.current&&currentIdentity.current===identity)setBusy(false);}
  }
  function appointments(cursor?:CoreCursor){if(connection)void run({action:'encounters',connection_sha256:connection.discovery.connection.connection_sha256,window,...(cursor?{cursor}:{})});}
  const connected=connection?.connection_status==='connected';
  const locked=busy||athenaBusy||setupBusy;
  return <section className="core-connection-setup" aria-label="Connect Cosmaneura">
    <h2>Connect Cosmaneura</h2>
    <p>Use your existing practice account and appointments. Your clinical records stay in Cosmaneura.</p>
    {error&&<p role="alert">{error}</p>}
    <button disabled={locked} onClick={()=>void run({action:'connection'})}>{busy?'Checking…':'Check connection status'}</button>
    {connection&&<div className="connection-practice">
      <h3>{connection.discovery.connection.practice_label}</h3>
      {connected?<p role="status">Connected to your practice.</p>:connection.connection_status==='review_required'?<p role="status">Your practice administrator needs to review this account connection.</p>:<>
        <p>Your signed-in account matches this practice. Confirm that this is the practice you want to use.</p>
        <button className="team-primary" disabled={locked} onClick={()=>void run({action:'connect',connection_sha256:connection.discovery.connection.connection_sha256})}>Connect this practice</button>
      </>}
    </div>}
    {connected&&<section aria-label="Cosmaneura appointments">
      <h3>Your appointments</h3><p>Choose a date range to view appointments available to your account.</p>
      <div className="connection-date-range"><label>From<input type="date" value={window.start_date} disabled={locked} onChange={e=>{setWindow({...window,start_date:e.target.value});setPage(null);}}/></label>
        <label>Before<input type="date" value={window.end_date} disabled={locked} onChange={e=>{setWindow({...window,end_date:e.target.value});setPage(null);}}/></label></div>
      <p className="team-fine">Up to 31 days, using the dates recorded by your practice.</p>
      <button disabled={locked} onClick={()=>appointments()}>View appointments</button>
      {appointmentSetupEnabled&&!busy&&!athenaBusy&&<CoreAppointmentSetupPanel identity={identity} connectionSha={connection.discovery.connection.connection_sha256} window={window} onBusyChange={setSetupBusy} onConnected={()=>setPage(null)} onAccessLost={cause=>{
        setConnection(null);setPage(null);setError('Practice access or appointments changed. Check your connection again.');
        if(cause instanceof WorkspaceApiError&&cause.status===401)onAuthenticationLost(cause);
      }}/>}
      {page&&openBlocked&&<p>Save or recover unfinished work before opening a notebook.</p>}
      {page&&<><ul className="connection-appointments">{page.discovery.encounters.map(entry=><li key={entry.appointment.appointment_ref}>
        <strong>{entry.patient.display_name}</strong><span>{entry.appointment.timezone_known?new Date(entry.appointment.appointment_date).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):entry.appointment.appointment_date.slice(0,19).replace('T',' ')}</span>
        {!entry.appointment.timezone_known&&<small>Time zone not supplied by the practice</small>}
        {onOpenNotebook&&<button disabled={locked||openBlocked} onClick={()=>void onOpenNotebook({action:'open',request_nonce:crypto.randomUUID(),connection_sha256:entry.connection_sha256,appointment_ref:entry.appointment.appointment_ref,source_sha256:entry.source_sha256})}>Open notebook</button>}
      </li>)}</ul>
        {!page.discovery.encounters.length&&<p>{page.discovery.next_cursor?'No available appointments on this page. Continue to check the next page.':'No available appointments in this part of the date range.'}</p>}
        {page.discovery.next_cursor&&<button disabled={locked} onClick={()=>appointments(page.discovery.next_cursor!)}>Next appointments</button>}
      </>}
    </section>}
    {athenaEnabled&&connected&&!busy&&!setupBusy&&<AthenaConnectionPanel key={connection.discovery.connection.connection_sha256} identity={identity} connectionSha={connection.discovery.connection.connection_sha256} connection={connection.discovery.connection} onOpenNotebook={onOpenNotebook} openBlocked={openBlocked} onBusyChange={setAthenaBusy} onAccessLost={cause=>{
      setConnection(null);setPage(null);setError('Practice access changed. Check your connection again.');
      if(cause instanceof WorkspaceApiError&&cause.status===401)onAuthenticationLost(cause);
    }}/>}
  </section>;
}
