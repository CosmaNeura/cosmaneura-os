import {useCallback,useEffect,useRef,useState} from 'react';
import {googleConnectionRequest,type GoogleAction,type GoogleStatus,type GoogleStart,type GoogleView} from './google-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {parseRecordNavigationResult,RECORD_NAVIGATION_EVENT} from './core-record-location';
import './microsoft-connection.css';

declare global {interface Window {cosmasGoogleNavigation?:{version:1;available:boolean;mode:'trusted-click'}}}
type PrivateState={owner:AuthenticatedWorkspaceIdentity;status:GoogleStatus|null;start:GoogleStart|null;view:GoogleView|null};
const when=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});

export function GoogleConnectionPanel({identity,onBusyChange,onAuthenticationLost}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(error:unknown)=>void}){
  const [data,setData]=useState<PrivateState|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[opening,setOpening]=useState(false);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const [unavailableFor,setUnavailableFor]=useState<AuthenticatedWorkspaceIdentity|null>(null);
  const owner=useRef(identity);owner.current=identity;
  // Hide prior-account values during render, before identity-change effects run.
  const visible=data?.owner===identity?data:null,status=visible?.status,start=visible?.start,view=visible?.view;
  const epoch=useRef(0),pending=useRef<AbortController|null>(null),navigationPending=useRef<string|null>(null),awaitingReturn=useRef(false);
  const denied=useRef(onAuthenticationLost);denied.current=onAuthenticationLost;
  const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
  const capability=window.cosmasGoogleNavigation;
  const nativeReady=!native||capability?.version===1&&capability.available&&capability.mode==='trusted-click';
  useSetupNavigationBusy(busy||opening,onBusyChange);
  useEffect(()=>{
    epoch.current++;pending.current?.abort();pending.current=null;navigationPending.current=null;awaitingReturn.current=false;
    setData(null);setMessage('');setBusy(false);setOpening(false);setUnavailableFor(null);
    return()=>{epoch.current++;pending.current?.abort();pending.current=null;};
  },[identity]);
  const run=useCallback(async(action:GoogleAction)=>{
    if(pending.current||owner.current!==identity)return;
    const current=++epoch.current,controller=new AbortController();pending.current=controller;setBusy(true);setMessage('');
    setData(previous=>previous?.owner===identity?{...previous,start:null,view:null}:null);
    try{
      const result=await googleConnectionRequest(identity,action,controller.signal);
      if(epoch.current!==current||owner.current!==identity)return;
      setUnavailableFor(null);
      if('authorization_url' in result){setData({owner:identity,status:null,start:result,view:null});setRequestId(crypto.randomUUID());setMessage('Continue with Google, then return here. Your connection will be checked when you return.');}
      else if('kind' in result)setData(previous=>({owner:identity,status:previous?.owner===identity?previous.status:null,start:null,view:result}));
      else if(result.state==='disconnected'){setData(null);setMessage('Google disconnected from CosmasOS. You can reconnect when ready.');}
      else setData({owner:identity,status:result,start:null,view:null});
    }catch(error){
      if(epoch.current!==current||owner.current!==identity)return;
      setData(null);
      if(error instanceof WorkspaceApiError&&[401,403].includes(error.status)){setMessage('Sign in to CosmasOS again to continue.');denied.current(error);}
      else if(error instanceof WorkspaceApiError&&error.status===409)setMessage('Google sign-in needs to finish or be renewed. Check your connection, then reconnect if needed.');
      else if(error instanceof WorkspaceApiError&&error.status===404){setUnavailableFor(identity);setMessage('Gmail accounts are not enabled for this practice yet.');}
      else setMessage('The result could not be confirmed. Check your connection before trying again.');
    }finally{if(epoch.current===current&&owner.current===identity){pending.current=null;setBusy(false);}}
  },[identity]);
  useEffect(()=>{void run('status');},[run]);
  useEffect(()=>{
    const returned=()=>{if(awaitingReturn.current&&document.visibilityState!=='hidden'&&!pending.current){awaitingReturn.current=false;void run('status');}};
    window.addEventListener('focus',returned);document.addEventListener('visibilitychange',returned);
    return()=>{window.removeEventListener('focus',returned);document.removeEventListener('visibilitychange',returned);};
  },[run]);
  useEffect(()=>{
    if(!start)return;
    const timer=setTimeout(()=>{setData(null);setMessage('That sign-in link expired. Check your connection or start again.');},Math.max(0,Date.parse(start.expires_at)-Date.now()));
    return()=>clearTimeout(timer);
  },[start]);
  useEffect(()=>{
    const receive=(event:Event)=>{
      if(!navigationPending.current||owner.current!==identity)return;
      const result=parseRecordNavigationResult((event as CustomEvent).detail,navigationPending.current);if(!result)return;
      navigationPending.current=null;setOpening(false);setRequestId(crypto.randomUUID());
      if(result.status!=='opened')setMessage('The browser handoff could not be confirmed. Check your browser before trying again.');
    };
    document.addEventListener(RECORD_NAVIGATION_EVENT,receive);return()=>document.removeEventListener(RECORD_NAVIGATION_EVENT,receive);
  },[identity]);
  useEffect(()=>{
    if(!opening)return;
    const timer=setTimeout(()=>{navigationPending.current=null;setOpening(false);setRequestId(crypto.randomUUID());setMessage('Complete sign-in in your browser, then check your connection here.');},15000);
    return()=>clearTimeout(timer);
  },[opening]);
  const begin=(event:{preventDefault:()=>void})=>{
    if(busy||opening||!start||owner.current!==identity||Date.parse(start.expires_at)<=Date.now()||native&&!native.isCurrent()){event.preventDefault();return;}
    awaitingReturn.current=true;
    if(native){navigationPending.current=requestId;setOpening(true);}
  };
  const blocked=busy||opening;
  return <section className="core-connection-setup microsoft-connection" aria-label="Gmail account">
    <header className="personal-connection-heading"><span className="settings-card-icon" aria-hidden="true">G</span><div><h2>Connect Gmail</h2><p>Your inbox, at a glance.</p></div></header>
    <p>Connect your Google account to see Gmail inbox summaries here. Google will ask you to approve access.</p>
    <p className="connection-access-summary">CosmasOS reads sender, subject, date and unread status. Message bodies and attachments stay in Gmail.</p>
    {!status?.account&&!start&&unavailableFor!==identity&&<ol className="personal-connection-steps"><li>Choose your Google account.</li><li>Review access on Google’s secure sign-in page.</li><li>Return here to read recent email.</li></ol>}
    <button disabled={blocked} onClick={()=>void run('status')}>{busy?'Working…':'Check Google connection'}</button>
    {status&&<div className="connection-practice">
      {status.account&&<><h3>{status.account.label}</h3><p>{status.account.email}</p></>}
      <p role="status">{status.state==='connected'?'Google connected.':status.state==='completing_sign_in'?'Completing Google sign-in…':status.state==='sign_in_pending'?'Google sign-in is ready to continue.':'Connect your Google account to continue.'}</p>
    </div>}
    {(!status||status.state!=='completing_sign_in')&&!start&&<button className="team-primary" disabled={blocked||!nativeReady||unavailableFor===identity} onClick={()=>void run('start')}>{status?.state==='connected'?'Reconnect Google':'Connect with Google'}</button>}
    {start&&<p>{native?<button type="button" className="team-primary" disabled={blocked||!nativeReady}
      data-google-connection={blocked?undefined:JSON.stringify({schemaVersion:1,requestId,expectedRevision:native.revision,href:start.authorization_url})}
      onClick={begin}>{opening?'Opening Google…':'Continue with Google'}</button>:
      <a className="team-primary microsoft-continue" href={start.authorization_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={begin} onAuxClick={begin}>Continue with Google</a>}</p>}
    {!nativeReady&&<p>Google connection is unavailable in this app build. Ask your practice administrator for the configured beta build.</p>}
    {status?.state==='connected'&&<div className="microsoft-actions"><button disabled={blocked} onClick={()=>void run('mail')}>Read recent email</button></div>}
    {(start||status&&status.state!=='sign_in_required')&&<button disabled={blocked} onClick={()=>void run('disconnect')}>{status?.state==='connected'?'Disconnect Google':'Cancel Google connection'}</button>}
    {view&&<section aria-label="Gmail inbox summaries">
      <h3>Inbox summaries</h3><p>{view.account.email} · Checked {when(view.observed_at)}</p>
      {view.items.length===0&&<p>Your inbox has no messages.</p>}
      <ul className="microsoft-items">{view.items.map((item,index)=><li key={`${index}:${item.id}`}><strong>{item.subject||'(No subject)'}</strong><span>{item.sender||'Sender unavailable'} · {when(item.received_at)}</span>{!item.is_read&&<small>Unread</small>}</li>)}</ul>
      {view.more&&<p>Showing up to 10 messages. More are available in Gmail.</p>}
    </section>}
    {message&&<p role="status">{message}</p>}
  </section>;
}
