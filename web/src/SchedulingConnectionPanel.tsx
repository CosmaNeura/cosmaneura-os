import {useCallback,useEffect,useRef,useState} from 'react';
import {SchedulingEnrollmentPanel} from './SchedulingEnrollmentPanel';
import {SCHEDULING_ENROLLMENT_BUILD} from './scheduling-enrollment-api';
import {schedulingLoginRequest,type SchedulingLoginStatus,type SchedulingLoginStart} from './scheduling-login-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {parseRecordNavigationResult,RECORD_NAVIGATION_EVENT} from './core-record-location';

declare global {interface Window {cosmasSchedulingNavigation?:{version:1;available:boolean;mode:'trusted-click'}}}

export function SchedulingConnectionPanel({identity,onBusyChange,onAuthenticationLost}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(error:unknown)=>void}){
  const [storedStatus,storeStatus]=useState<{identity:AuthenticatedWorkspaceIdentity;value:SchedulingLoginStatus}|null>(null),[storedStart,storeStart]=useState<{identity:AuthenticatedWorkspaceIdentity;value:SchedulingLoginStart}|null>(null);
  const status=storedStatus?.identity===identity?storedStatus.value:null,start=storedStart?.identity===identity?storedStart.value:null;
  const setStatus=(value:SchedulingLoginStatus|null)=>storeStatus(value?{identity,value}:null),setStart=(value:SchedulingLoginStart|null)=>storeStart(value?{identity,value}:null);
  const [enrollmentOwner,setEnrollmentOwner]=useState<AuthenticatedWorkspaceIdentity|null>(null),[enrollmentBusy,setEnrollmentBusy]=useState(false);
  const currentIdentity=useRef(identity);currentIdentity.current=identity;
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[opening,setOpening]=useState(false);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const epoch=useRef(0),pending=useRef<AbortController|null>(null),navigationPending=useRef<string|null>(null),awaitingReturn=useRef(false);
  const denied=useRef(onAuthenticationLost);denied.current=onAuthenticationLost;
  const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
  const capability=window.cosmasSchedulingNavigation;
  const nativeReady=!native||capability?.version===1&&capability.available&&capability.mode==='trusted-click';
  useSetupNavigationBusy(busy||opening||enrollmentBusy,onBusyChange);
  useEffect(()=>{
    epoch.current++;pending.current?.abort();pending.current=null;navigationPending.current=null;awaitingReturn.current=false;
    setStatus(null);setStart(null);setEnrollmentOwner(null);setEnrollmentBusy(false);setMessage('');setBusy(false);setOpening(false);
    return()=>{epoch.current++;pending.current?.abort();pending.current=null;};
  },[identity]);
  const run=useCallback(async(action:'status'|'start'|'disconnect')=>{
    if(pending.current)return;
    const current=++epoch.current,controller=new AbortController();pending.current=controller;setBusy(true);setMessage('');setStart(null);
    try{
      const result=await schedulingLoginRequest(identity,action,controller.signal);
      if(epoch.current!==current||currentIdentity.current!==identity)return;
      if('authorization_url' in result){setStart(result);setRequestId(crypto.randomUUID());setMessage('Continue with Google, then return to CosmasOS. Your connection will be checked when you return.');}
      else if(result.state==='disconnected'){setStatus(null);setMessage('Scheduling disconnected from CosmasOS. You can reconnect when ready.');}
      else {setStatus(result);setEnrollmentOwner(null);}
    }catch(error){
      if(epoch.current!==current||currentIdentity.current!==identity)return;
      setStatus(null);
      if(error instanceof WorkspaceApiError&&[401,403].includes(error.status)){setMessage('Sign in to CosmasOS again to continue.');denied.current(error);}
      else if(error instanceof WorkspaceApiError&&error.status===409){if(SCHEDULING_ENROLLMENT_BUILD)setEnrollmentOwner(identity);else setMessage('Your Scheduling account needs review, or a sign-in is still completing. Check again; ask your practice administrator if this persists.');}
      else if(error instanceof WorkspaceApiError&&error.status===404)setMessage('Scheduling sign-in is not enabled for this practice yet.');
      else setMessage('The connection result could not be confirmed. Check status before trying again.');
    }finally{if(epoch.current===current&&currentIdentity.current===identity){pending.current=null;setBusy(false);}}
  },[identity]);
  useEffect(()=>{void run('status');},[run]);
  useEffect(()=>{
    const returned=()=>{if(awaitingReturn.current&&document.visibilityState!=='hidden'&&!pending.current){awaitingReturn.current=false;void run('status');}};
    window.addEventListener('focus',returned);document.addEventListener('visibilitychange',returned);
    return()=>{window.removeEventListener('focus',returned);document.removeEventListener('visibilitychange',returned);};
  },[run]);
  useEffect(()=>{
    if(!start)return;
    const timer=setTimeout(()=>{setStart(null);setMessage('That sign-in link expired. Check your connection or start again.');},Math.max(0,Date.parse(start.expires_at)-Date.now()));
    return()=>clearTimeout(timer);
  },[start]);
  useEffect(()=>{
    const receive=(event:Event)=>{
      if(!navigationPending.current)return;
      const result=parseRecordNavigationResult((event as CustomEvent).detail,navigationPending.current);if(!result)return;
      navigationPending.current=null;setOpening(false);setRequestId(crypto.randomUUID());
      if(result.status!=='opened')setMessage('The browser handoff could not be confirmed. Check your browser before trying again.');
    };
    document.addEventListener(RECORD_NAVIGATION_EVENT,receive);return()=>document.removeEventListener(RECORD_NAVIGATION_EVENT,receive);
  },[]);
  useEffect(()=>{
    if(!opening)return;
    const timer=setTimeout(()=>{navigationPending.current=null;setOpening(false);setRequestId(crypto.randomUUID());setMessage('Check your browser to complete sign-in, then check your connection here.');},15000);
    return()=>clearTimeout(timer);
  },[opening]);
  const begin=(event:{preventDefault:()=>void})=>{
    if(busy||opening||!start||Date.parse(start.expires_at)<=Date.now()||native&&!native.isCurrent()){event.preventDefault();return;}
    awaitingReturn.current=true;
    if(native){navigationPending.current=requestId;setOpening(true);}
  };
  const blocked=busy||opening||enrollmentBusy;
  return <section className="core-connection-setup" aria-label="Scheduling connection">
    <h2>Connect Scheduling</h2><p>Use the Google account approved for your Scheduling practice. Your appointments remain in Scheduling.</p>
    <button disabled={blocked} onClick={()=>void run('status')}>{busy?'Working…':'Check Scheduling connection'}</button>
    {status&&<div className="connection-practice"><h3>{status.label}</h3><p role="status">{status.state==='connected'?'Connected to Scheduling.':status.state==='completing_sign_in'?'Completing Google sign-in…':status.state==='sign_in_pending'?'Google sign-in is ready to continue.':'Sign in with Google to use this Scheduling account.'}</p></div>}
    {status&&status.state!=='completing_sign_in'&&<button disabled={blocked||!nativeReady} onClick={()=>void run('start')}>{status.state==='connected'?'Sign in again':'Connect with Google'}</button>}
    {start&&<p>{native?<button type="button" className="team-primary" disabled={blocked||!nativeReady}
      data-scheduling-sign-in={blocked?undefined:JSON.stringify({schemaVersion:1,requestId,expectedRevision:native.revision,href:start.authorization_url})}
      onClick={begin}>{opening?'Opening Google…':'Continue with Google'}</button>:
      <a style={{display:'inline-flex',alignItems:'center',minHeight:44}} className="team-primary" href={start.authorization_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={begin} onAuxClick={begin}>Continue with Google</a>}</p>}
    {!nativeReady&&<p>Google sign-in is unavailable in this app build. Ask your practice administrator for the configured beta build.</p>}
    {(start||status&&status.state!=='sign_in_required')&&<button disabled={blocked} onClick={()=>void run('disconnect')}>{status?.state==='connected'?'Disconnect Scheduling':'Cancel Scheduling sign-in'}</button>}
    {enrollmentOwner===identity&&!busy&&<SchedulingEnrollmentPanel identity={identity} onBusyChange={setEnrollmentBusy} onAuthenticationLost={onAuthenticationLost} onConnected={()=>{setEnrollmentOwner(null);void run('status');}}/>}
    {message&&<p role="status">{message}</p>}
  </section>;
}
