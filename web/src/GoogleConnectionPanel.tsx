import {useCallback,useEffect,useRef,useState} from 'react';
import {googleConnectionRequest,type GoogleAction,type GoogleStatus,type GoogleStart,type GoogleView} from './google-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {parseRecordNavigationResult,RECORD_NAVIGATION_EVENT} from './core-record-location';
import {useConnectionReturnCheck} from './use-connection-return-check';
import {PersonalConnectionHealth} from './PersonalConnectionHealth';
import {observeConnectionStatus,observeConnectionRead,connectionReadScope,connectionReadFailed,connectionCheckFailed,invalidateConnectionHealth,personalConnectionProgress,type ConnectionReadScope} from './connection-operation-health';
import './microsoft-connection.css';

declare global {interface Window {cosmasGoogleNavigation?:{version:1;available:boolean;mode:'trusted-click'}}}
type PrivateState={owner:AuthenticatedWorkspaceIdentity;status:GoogleStatus|null;start:GoogleStart|null;view:GoogleView|null};
const when=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});

export function GoogleConnectionPanel({identity,onBusyChange,onAuthenticationLost}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(error:unknown)=>void}){
  const [data,setData]=useState<PrivateState|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[opening,setOpening]=useState(false);
  const [action,setAction]=useState<string|null>(null);
  const operation=useRef<{action:GoogleAction;scope:ConnectionReadScope|null}|null>(null);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const [unavailableFor,setUnavailableFor]=useState<AuthenticatedWorkspaceIdentity|null>(null);
  const owner=useRef(identity);owner.current=identity;
  // Hide prior-account values during render, before identity-change effects run.
  const visible=data?.owner===identity?data:null,status=visible?.status,start=visible?.start,view=visible?.view;
  const epoch=useRef(0),pending=useRef<AbortController|null>(null),navigationPending=useRef<string|null>(null);
  const denied=useRef(onAuthenticationLost);denied.current=onAuthenticationLost;
  const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
  const capability=window.cosmasGoogleNavigation;
  const nativeReady=!native||capability?.version===1&&capability.available&&capability.mode==='trusted-click';
  useSetupNavigationBusy(opening||busy&&(action==='start'||action==='disconnect'),onBusyChange);
  useEffect(()=>{
    epoch.current++;pending.current?.abort();pending.current=null;navigationPending.current=null;
    setData(null);setMessage('');setBusy(false);setAction(null);operation.current=null;setOpening(false);setUnavailableFor(null);
    return()=>{epoch.current++;pending.current?.abort();pending.current=null;invalidateConnectionHealth(identity,'google');};
  },[identity]);
  const run=useCallback(async(action:GoogleAction)=>{
    if(owner.current!==identity)return;
    if(pending.current)return 'busy' as const;
    const current=++epoch.current,controller=new AbortController();pending.current=controller;setBusy(true);setAction(action);setMessage('');
    const scope=connectionReadScope(identity,'google');operation.current={action,scope};
    if(action==='start'||action==='disconnect')invalidateConnectionHealth(identity,'google');
    setData(previous=>previous?.owner===identity?{...previous,start:null,view:null}:null);
    try{
      const result=await googleConnectionRequest(identity,action,controller.signal);
      if(epoch.current!==current||owner.current!==identity)return;
      setUnavailableFor(null);
      if('authorization_url' in result){setData({owner:identity,status:null,start:result,view:null});setRequestId(crypto.randomUUID());setMessage('Continue with Google, then return here. Your connection will be checked when you return.');}
      else if('kind' in result){
        if(!observeConnectionRead(identity,'google',scope,result)){invalidateConnectionHealth(identity,'google');setData(null);setMessage('The connected account or its permissions changed. Check your connection before reading again.');return;}
        setData(previous=>({owner:identity,status:previous?.owner===identity?previous.status:null,start:null,view:result}));
      }
      else if(result.state==='disconnected'){setData(null);setMessage('Google disconnected from CosmasOS. You can reconnect when ready.');}
      else {observeConnectionStatus(identity,'google',result);setData({owner:identity,status:result,start:null,view:null});return result.state;}
    }catch(error){
      if(epoch.current!==current||owner.current!==identity)return;
      setData(null);
      if(action==='mail'||action==='calendar')connectionReadFailed(identity,'google',scope,action);
      connectionCheckFailed(identity,'google');
      // Recheck connection state, never replay the failed read.
      if((action==='mail'||action==='calendar')&&!(error instanceof WorkspaceApiError&&[401,403,404].includes(error.status))){
        const content=action==='mail'?'Email':'Calendar';
        const needsCalendar=error instanceof WorkspaceApiError&&error.code==='google_calendar_consent_required';
        setMessage(content+' could not be loaded. Checking your connection…');
        setAction('recovery');
        const recoveryTimer=setTimeout(()=>controller.abort(),10000);
        try{
          const checked=await googleConnectionRequest(identity,'status',controller.signal);
          if(epoch.current!==current||owner.current!==identity)return;
          if('state' in checked&&checked.state!=='disconnected'){
            const calendarMissing=needsCalendar&&checked.state==='connected'&&checked.capabilities?.calendar!==true;
            const recovered=calendarMissing&&!checked.capabilities?{...checked,capabilities:{mail:true,calendar:false}}:checked;
            observeConnectionStatus(identity,'google',recovered);setData({owner:identity,status:recovered,start:null,view:null});
            setMessage(checked.state==='connected'?(calendarMissing?'Email is connected. Choose Add calendar access to view your week.':
              content+' could not be loaded. Your account is still connected. Try again.'):
              checked.state==='sign_in_required'?'Connect your Google account again to continue.':'Finish Google sign-in, then try again.');
            return;
          }
        }catch(recoveryError){
          if(epoch.current!==current||owner.current!==identity)return;
          error=recoveryError;
        }finally{clearTimeout(recoveryTimer);}
      }
      if(error instanceof WorkspaceApiError&&[401,403].includes(error.status)){invalidateConnectionHealth(identity,'google');setMessage('Sign in to CosmasOS again to continue.');denied.current(error);}
      else if(error instanceof WorkspaceApiError&&error.status===409)setMessage('Google sign-in needs to finish or be renewed. Check your connection, then reconnect if needed.');
      else if(error instanceof WorkspaceApiError&&error.status===404){setUnavailableFor(identity);setMessage('Gmail accounts are not enabled for this practice yet.');}
      else setMessage('The result could not be confirmed. Check your connection before trying again.');
    }finally{if(epoch.current===current&&owner.current===identity){pending.current=null;operation.current=null;setBusy(false);setAction(null);}}
  },[identity]);
  useEffect(()=>{void run('status');},[run]);
  const returnCheck=useConnectionReturnCheck(identity,()=>run('status'),last=>setMessage(last==='sign_in_pending'
    ?'CosmaBot has not received the Google sign-in result. Finish in your browser, then check the connection here.'
    :'CosmaBot has not confirmed the Google connection. Check the connection again to see the latest result.'));
  const manual=(action:GoogleAction)=>{returnCheck.cancel();void run(action);};
  const cancelRead=()=>{
    const active=operation.current;if(!active||active.action==='start'||active.action==='disconnect')return;
    returnCheck.cancel();epoch.current++;pending.current?.abort();pending.current=null;operation.current=null;
    if(active.action==='mail'||active.action==='calendar')connectionReadFailed(identity,'google',active.scope,active.action,true);
    else {connectionCheckFailed(identity,'google');setData(null);}
    setBusy(false);setAction(null);setMessage('Stopped waiting. No late result will be shown. You can check the connection or read again when ready.');
  };
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
    returnCheck.begin();
    if(native){navigationPending.current=requestId;setOpening(true);}
  };
  const blocked=busy||opening;
  const calendarNeedsPermission=status?.state==='connected'&&status.capabilities?.calendar===false;
  return <section className="core-connection-setup microsoft-connection" aria-label="Google email and calendar">
    <header className="personal-connection-heading"><span className="settings-card-icon" aria-hidden="true">G</span><div><h2>{status?.state==='connected'?'Google Workspace':'Connect Google Workspace'}</h2><p>Email and the week ahead.</p></div></header>
    <p>{status?.state==='connected'?'Your account is connected. Check email and calendar access below.':'Connect your Google account to see Gmail inbox summaries and your primary calendar here. Google will ask you to approve access.'}</p>
    <p className="connection-access-summary">CosmaBot reads email headers and event titles and times. Message bodies and attachments stay in Gmail. It cannot send email or change calendar events.</p>
    {!status?.account&&!start&&unavailableFor!==identity&&<details><summary>How to connect</summary><ol className="personal-connection-steps"><li>Choose your Google account.</li><li>Review access on Google’s secure sign-in page.</li><li>Return here to read recent email.</li></ol></details>}
    <button disabled={blocked} onClick={()=>manual('status')}>Check Google connection</button>
    {busy&&action&&<div className="connection-progress" role="status"><p>{personalConnectionProgress('google',action)}</p>
      <small>{action==='recovery'?'Account recovery has a 10-second limit. The read will not repeat.':'This request has a 50-second limit.'} {action==='status'||action==='mail'||action==='calendar'||action==='recovery'?'You can keep working elsewhere.':''}</small>
      {action!=='start'&&action!=='disconnect'&&<button onClick={cancelRead}>Stop waiting</button>}</div>}
    {status&&<div className="connection-practice">
      {status.account&&<><h3>{status.account.label}</h3><p>{status.account.email}</p></>}
      <p role="status">{status.state==='connected'?'Google connected.':status.state==='completing_sign_in'?'Completing Google sign-in…':status.state==='sign_in_pending'?'Google sign-in is ready to continue.':'Connect your Google account to continue.'}</p>
    </div>}
    {(!status||status.state!=='completing_sign_in')&&!start&&<button className="team-primary" disabled={blocked||!nativeReady||unavailableFor===identity} onClick={()=>manual('start')}>{calendarNeedsPermission?'Add calendar access':status?.state==='connected'?'Reconnect Google':'Connect with Google'}</button>}
    {start&&<p>{native?<button type="button" className="team-primary" disabled={blocked||!nativeReady}
      data-google-connection={blocked?undefined:JSON.stringify({schemaVersion:1,requestId,expectedRevision:native.revision,href:start.authorization_url})}
      onClick={begin}>{opening?'Opening Google…':'Continue with Google'}</button>:
      <a className="team-primary microsoft-continue" href={start.authorization_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={begin} onAuxClick={begin}>Continue with Google</a>}</p>}
    {!nativeReady&&<p>Google connection is unavailable in this app build. Ask your practice administrator for the configured beta build.</p>}
    {status?.state==='connected'&&<PersonalConnectionHealth identity={identity} provider="google"
      mailAction={<button disabled={blocked} onClick={()=>manual('mail')}>Read recent email</button>}
      calendarAction={calendarNeedsPermission?<span>Choose Add calendar access above.</span>:<button disabled={blocked} onClick={()=>manual('calendar')}>View next 7 days</button>}/> }
    {(start||status&&status.state!=='sign_in_required')&&<button disabled={blocked} onClick={()=>manual('disconnect')}>{status?.state==='connected'?'Disconnect Google':'Cancel Google connection'}</button>}
    {view?.kind==='mail'&&<section aria-label="Gmail inbox summaries">
      <h3>Inbox summaries</h3><p>{view.account.email} · Checked {when(view.observed_at)}</p>
      {view.items.length===0&&<p>Your inbox has no messages.</p>}
      <ul className="microsoft-items">{view.items.map((item,index)=><li key={`${index}:${item.id}`}><strong>{item.subject||'(No subject)'}</strong><span>{item.sender||'Sender unavailable'} · {when(item.received_at)}</span>{!item.is_read&&<small>Unread</small>}</li>)}</ul>
      {view.more&&<p>Showing up to 10 messages. More are available in Gmail.</p>}
    </section>}
    {view?.kind==='calendar'&&<section aria-label="Upcoming Google events">
      <h3>Next 7 days</h3><p>{view.account.email} · Checked {when(view.observed_at)}</p>
      {view.items.length===0&&<p>No events in the next 7 days.</p>}
      <ul className="microsoft-items">{view.items.map(item=><li key={item.id}><strong>{item.subject||'(Untitled event)'}</strong>
        <span>{item.all_day?new Date(item.starts_at+'T12:00:00Z').toLocaleDateString(undefined,{dateStyle:'medium',timeZone:'UTC'}):when(item.starts_at)+' – '+when(item.ends_at)}</span>
        {item.all_day&&<small>All day</small>}{item.cancelled&&<small>Cancelled</small>}</li>)}</ul>
      {view.more&&<p>Showing up to 25 events. More are available in Google Calendar.</p>}
    </section>}
    {message&&<p role="status">{message}</p>}
  </section>;
}
