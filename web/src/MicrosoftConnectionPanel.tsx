import {useCallback,useEffect,useRef,useState} from 'react';
import {microsoftConnectionRequest,type MicrosoftAction,type MicrosoftStatus,type MicrosoftStart,type MicrosoftView} from './microsoft-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {parseRecordNavigationResult,RECORD_NAVIGATION_EVENT} from './core-record-location';
import {useConnectionReturnCheck} from './use-connection-return-check';
import {useGoogleNativeForeground as usePersonalConnectionNativeForeground} from './use-google-native-foreground';
import {PersonalConnectionHealth} from './PersonalConnectionHealth';
import {connectionHealth,useConnectionHealth,observeConnectionStatus,observeConnectionRead,connectionReadScope,connectionReadFailed,connectionCheckFailed,invalidateConnectionHealth,personalConnectionProgress,type ConnectionHealth,type ConnectionReadScope} from './connection-operation-health';
import './microsoft-connection.css';

declare global {interface Window {cosmasMicrosoftNavigation?:{version:1;available:boolean;mode:'trusted-click'}}}
type MicrosoftService='mail'|'calendar';
type MicrosoftViews={mail?:Extract<MicrosoftView,{kind:'mail'}>;calendar?:Extract<MicrosoftView,{kind:'calendar'}>};
type PrivateState={owner:AuthenticatedWorkspaceIdentity;status:MicrosoftStatus|null;start:MicrosoftStart|null;views:MicrosoftViews;scope:ConnectionReadScope|null};
const when=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
const accountChanged='The connected account or its permissions changed. Check your connection before reading again.';
function sameObservedAccount(identity:AuthenticatedWorkspaceIdentity,expected:ConnectionHealth){
  const current=connectionHealth(identity,'microsoft');
  // A same-grant directory check may refresh health without invalidating reads.
  // With no checked grant, every newer observation supersedes the pending check.
  return expected.accountCurrent&&expected.connected&&expected.accountVersion!==null
    ?current.accountCurrent&&current.connected&&current.accountVersion===expected.accountVersion
    :current===expected;
}
function checkedState(identity:AuthenticatedWorkspaceIdentity,previous:PrivateState|null,status:MicrosoftStatus):PrivateState{
  const scope=connectionReadScope(identity,'microsoft');
  // Only this exact account and grant may retain its dated read results.
  return {owner:identity,status,start:null,scope,views:scope&&previous?.owner===identity&&previous.scope===scope?previous.views:{}};
}

export function MicrosoftConnectionPanel({identity,onBusyChange,onAuthenticationLost}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(error:unknown)=>void}){
  const [data,setData]=useState<PrivateState|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[opening,setOpening]=useState(false);
  const [service,setService]=useState<MicrosoftService>('mail');
  const latest=useRef(data);latest.current=data;
  const [action,setAction]=useState<string|null>(null);
  const operation=useRef<{action:MicrosoftAction;scope:ConnectionReadScope|null;health:ConnectionHealth}|null>(null);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const [unavailableFor,setUnavailableFor]=useState<AuthenticatedWorkspaceIdentity|null>(null);
  const owner=useRef(identity);owner.current=identity;
  const health=useConnectionHealth(identity,'microsoft');
  const [needsCheck,setNeedsCheck]=useState(false);
  const epoch=useRef(0),pending=useRef<AbortController|null>(null),navigationPending=useRef<string|null>(null);
  const denied=useRef(onAuthenticationLost);denied.current=onAuthenticationLost;
  const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
  const capability=window.cosmasMicrosoftNavigation;
  const nativeReady=!native||capability?.version===1&&capability.available&&capability.mode==='trusted-click';
  useSetupNavigationBusy(opening||busy&&(action==='start'||action==='disconnect'),onBusyChange);
  useEffect(()=>{
    epoch.current++;pending.current?.abort();pending.current=null;navigationPending.current=null;
    setData(null);setService('mail');setMessage('');setBusy(false);setAction(null);operation.current=null;setOpening(false);setUnavailableFor(null);
    return()=>{epoch.current++;pending.current?.abort();pending.current=null;invalidateConnectionHealth(identity,'microsoft');};
  },[identity]);
  useEffect(()=>{
    // Settings keeps this editor mounted while directory checks may change its account.
    setData(previous=>previous?.owner===identity&&previous.scope!==connectionReadScope(identity,'microsoft')?null:previous);
    const active=operation.current;
    if(active&&!sameObservedAccount(identity,active.health)){
      epoch.current++;pending.current?.abort();pending.current=null;operation.current=null;
      setData(null);setBusy(false);setAction(null);setMessage(accountChanged);
    }
  },[identity,health]);
  const run=useCallback(async(action:MicrosoftAction)=>{
    if(owner.current!==identity||!nativeForeground.foreground.current)return;
    if(pending.current)return 'busy' as const;
    const previous=latest.current?.owner===identity?latest.current:null;
    const current=++epoch.current,controller=new AbortController();pending.current=controller;setBusy(true);setAction(action);setMessage('');
    const scope=connectionReadScope(identity,'microsoft');
    if(action==='start'||action==='disconnect')invalidateConnectionHealth(identity,'microsoft');
    const active={action,scope,health:connectionHealth(identity,'microsoft')};operation.current=active;
    const accept=()=>{
      if(epoch.current!==current||owner.current!==identity)return false;
      if(sameObservedAccount(identity,active.health))return true;
      controller.abort();setData(null);setMessage(accountChanged);return false;
    };
    // Record our own synchronous health publications before effects observe them.
    const published=()=>{active.health=connectionHealth(identity,'microsoft');};
    setData(previous=>action==='start'||action==='disconnect'?null:previous?.owner===identity?{...previous,start:null}:null);
    try{
      const result=await microsoftConnectionRequest(identity,action,controller.signal);
      if(!accept())return;
      setUnavailableFor(null);setNeedsCheck(false);
      if('authorization_url' in result){setData({owner:identity,status:null,start:result,views:{},scope:null});setRequestId(crypto.randomUUID());setMessage('Continue with Microsoft, then return here. Your connection will be checked when you return.');}
      else if('kind' in result){
        if(!observeConnectionRead(identity,'microsoft',scope,result)){invalidateConnectionHealth(identity,'microsoft');published();setData(null);setMessage(accountChanged);return;}
        published();
        setData(previous=>({owner:identity,status:previous?.owner===identity?previous.status:null,start:null,scope,
          views:{...(previous?.owner===identity&&previous.scope===scope?previous.views:{}),
            ...(result.kind==='mail'?{mail:result}:{calendar:result})}}));
      }
      else if(result.state==='disconnected'){setData(null);setMessage('Microsoft disconnected from CosmasOS. You can reconnect when ready.');}
      else {observeConnectionStatus(identity,'microsoft',result);published();setData(checkedState(identity,previous,result));return result.state;}
    }catch(error){
      if(!accept())return;
      setData(null);
      if(action==='mail'||action==='calendar')connectionReadFailed(identity,'microsoft',scope,action);
      connectionCheckFailed(identity,'microsoft');
      published();
      // Recheck connection state, never replay the failed mailbox/calendar read.
      if((action==='mail'||action==='calendar')&&!(error instanceof WorkspaceApiError&&[401,403,404].includes(error.status))){
        const content=action==='mail'?'Email':'Calendar';
        setMessage(`${content} could not be loaded. Checking your connection…`);
        setAction('recovery');
        const recoveryTimer=setTimeout(()=>controller.abort(),10000);
        try{
          const checked=await microsoftConnectionRequest(identity,'status',controller.signal);
          if(!accept())return;
          if('state' in checked&&checked.state!=='disconnected'){
            observeConnectionStatus(identity,'microsoft',checked);published();setData(checkedState(identity,previous,checked));
            setMessage(checked.state==='connected'?`${content} could not be loaded. Your account is still connected. Check that it has an Outlook or Exchange mailbox. If your email and calendar are hosted by Google, use Google Workspace.`:
              checked.state==='sign_in_required'?`Connect your Microsoft account again to load ${content.toLowerCase()}.`:'Finish Microsoft sign-in, then try again.');
            return;
          }
        }catch(recoveryError){
          if(!accept())return;
          error=recoveryError;
        }finally{clearTimeout(recoveryTimer);}
      }
      if(error instanceof WorkspaceApiError&&[401,403].includes(error.status)){invalidateConnectionHealth(identity,'microsoft');setMessage('Sign in to CosmasOS again to continue.');denied.current(error);}
      else if(error instanceof WorkspaceApiError&&error.status===409)setMessage('Microsoft sign-in needs to finish or be renewed. Check your connection, then reconnect if needed.');
      else if(error instanceof WorkspaceApiError&&error.status===404){setUnavailableFor(identity);setMessage('Microsoft email and calendar are not enabled for this practice yet.');}
      else setMessage('The result could not be confirmed. Check your connection before trying again.');
    }finally{if(epoch.current===current&&owner.current===identity){pending.current=null;operation.current=null;setBusy(false);setAction(null);}}
  },[identity]);
  useEffect(()=>{void run('status');},[run]);
  const returnCheck=useConnectionReturnCheck(identity,()=>run('status'),last=>setMessage(last==='sign_in_pending'
    ?'CosmaBot has not received the Microsoft sign-in result. Finish in your browser, then check the connection here.'
    :'CosmaBot has not confirmed the Microsoft connection. Check the connection again to see the latest result.'),
    identity.mode==='clerk_jwt'&&!!identity.nativeSession);
  // Reuse the identity-scoped native hook; it has no Google-specific behavior.
  const nativeForeground=usePersonalConnectionNativeForeground(identity,{
    suspended:()=>{
      returnCheck.suspend();epoch.current++;pending.current?.abort();pending.current=null;operation.current=null;
      setBusy(false);setAction(null);setNeedsCheck(true);setData(previous=>previous?{...previous,views:{}}:null);
    },
    resumed:()=>{
      navigationPending.current=null;setOpening(false);
      const checkingOAuth=returnCheck.hasActive();returnCheck.resume();
      if(!checkingOAuth)void run('status');
    },
  });
  // Hide before effects run, including changes observed by the connection directory.
  const visible=!nativeForeground.suspended&&!needsCheck&&data?.owner===identity&&data.scope===connectionReadScope(identity,'microsoft')?data:null,
    status=visible?.status,start=visible?.start,view=visible?.views[service];
  const manual=(action:MicrosoftAction)=>{returnCheck.cancel();if(action==='mail'||action==='calendar')setService(action);void run(action);};
  const cancelRead=()=>{
    const active=operation.current;if(!active||active.action==='start'||active.action==='disconnect')return;
    returnCheck.cancel();epoch.current++;pending.current?.abort();pending.current=null;operation.current=null;
    if(active.action==='mail'||active.action==='calendar')connectionReadFailed(identity,'microsoft',active.scope,active.action,true);
    else {connectionCheckFailed(identity,'microsoft');setData(null);}
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
  const blocked=busy||opening||nativeForeground.suspended;
  return <section className="core-connection-setup microsoft-connection" aria-label="Microsoft email and calendar">
    <header className="personal-connection-heading"><span className="settings-card-icon" aria-hidden="true">M</span><div><h2>{status?.state==='connected'?'Microsoft':'Connect Microsoft'}</h2><p>Email and the week ahead.</p></div></header>
    <p>{status?.state==='connected'?'Your account is connected. Check Outlook email and calendar access below.':'Connect your work account to see Outlook email and upcoming calendar events here. Microsoft will ask you to approve access.'}</p>
    <p className="connection-access-summary">This connection is read-only. It cannot send email, change appointments or update your clinical records.</p>
    {nativeForeground.suspended&&<p role="status">Microsoft details are hidden while the app is inactive. Your saved work is retained.</p>}
    {!status?.account&&!start&&unavailableFor!==identity&&<details><summary>How to connect</summary><ol className="personal-connection-steps"><li>Choose your Microsoft work or school account.</li><li>Review access on Microsoft’s secure sign-in page.</li><li>Return here to view your inbox or upcoming events.</li></ol></details>}
    <button disabled={blocked} onClick={()=>manual('status')}>Check Microsoft connection</button>
    {busy&&action&&<div className="connection-progress" role="status"><p>{personalConnectionProgress('microsoft',action)}</p>
      <small>{action==='recovery'?'Account recovery has a 10-second limit. The read will not repeat.':'This request has a 50-second limit.'} {action==='status'||action==='mail'||action==='calendar'||action==='recovery'?'You can keep working elsewhere.':''}</small>
      {action!=='start'&&action!=='disconnect'&&<button onClick={cancelRead}>Stop waiting</button>}</div>}
    {status&&<div className="connection-practice">
      {status.account&&<><h3>{status.account.label}</h3><p>{status.account.email}</p></>}
      <p role="status">{status.state==='connected'?'Microsoft connected.':status.state==='completing_sign_in'?'Completing Microsoft sign-in…':status.state==='sign_in_pending'?'Microsoft sign-in is ready to continue.':'Connect your Microsoft account to continue.'}</p>
    </div>}
    {(!status||status.state!=='completing_sign_in'&&status.state!=='connected')&&!start&&<button className="team-primary" disabled={blocked||!nativeReady||unavailableFor===identity} onClick={()=>manual('start')}>Connect with Microsoft</button>}
    {start&&<p>{native?<button type="button" className="team-primary" disabled={blocked||!nativeReady}
      data-microsoft-connection={blocked?undefined:JSON.stringify({schemaVersion:1,requestId,expectedRevision:native.revision,href:start.authorization_url})}
      onClick={begin}>{opening?'Opening Microsoft…':'Continue with Microsoft'}</button>:
      <a className="team-primary microsoft-continue" href={start.authorization_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={begin} onAuxClick={begin}>Continue with Microsoft</a>}</p>}
    {!nativeReady&&<p>Microsoft connection is unavailable in this app build. Ask your practice administrator for the configured beta build.</p>}
    {status?.state==='connected'&&<>
      <div className="microsoft-service-tabs" role="group" aria-label="Choose Microsoft service">
        <button disabled={blocked} aria-pressed={service==='mail'} onClick={()=>setService('mail')}>Email</button>
        <button disabled={blocked} aria-pressed={service==='calendar'} onClick={()=>setService('calendar')}>Calendar</button>
      </div>
      <PersonalConnectionHealth identity={identity} provider="microsoft"
        mailAction={<button className={service==='mail'?'team-primary':undefined} disabled={blocked} onClick={()=>manual('mail')}>{visible?.views.mail?'Refresh email':'Read recent email'}</button>}
        calendarAction={<button className={service==='calendar'?'team-primary':undefined} disabled={blocked} onClick={()=>manual('calendar')}>{visible?.views.calendar?'Refresh calendar':'View next 7 days'}</button>}/>
      {!view&&<p className="microsoft-results-hint">{service==='mail'?'Read recent email to see up to 25 inbox headers.':'View the next 7 days to see event titles and times.'}</p>}
    </>}
    {(start||status&&status.state!=='connected'&&status.state!=='sign_in_required')&&<button disabled={blocked} onClick={()=>manual('disconnect')}>Cancel Microsoft connection</button>}
    {view&&<section aria-label={view.kind==='mail'?'Recent Outlook email':'Upcoming Outlook events'}>
      <h3>{view.kind==='mail'?'Recent email':'Next 7 days'}</h3><p>{view.kind==='mail'?'Email headers':'Calendar summaries'} · Last loaded {when(view.observed_at)}</p>
      {view.items.length===0&&<p>{view.kind==='mail'?'Your inbox has no messages.':'No events in the next 7 days.'}</p>}
      <ul className="microsoft-items">{view.kind==='mail'?view.items.map((item,index)=><li key={`${index}:${item.id}`}><strong>{item.subject||'(No subject)'}</strong><span>{item.sender||'Sender unavailable'} · {when(item.received_at)}</span>{!item.is_read&&<small>Unread</small>}</li>):
        view.items.map((item,index)=><li key={`${index}:${item.id}`}><strong>{item.subject||'(Untitled event)'}</strong><span>{when(item.starts_at)} – {when(item.ends_at)}</span>{item.all_day&&<small>All day</small>}{item.cancelled&&<small>Cancelled</small>}</li>)}</ul>
      {view.more&&<p>Showing the first 25. More are available in Outlook.</p>}
    </section>}
    {status?.state==='connected'&&<details className="microsoft-account-controls"><summary>Manage Microsoft account</summary>
      <div className="microsoft-actions"><button disabled={blocked||!nativeReady} onClick={()=>manual('start')}>Reconnect Microsoft</button>
        <button disabled={blocked} onClick={()=>manual('disconnect')}>Disconnect Microsoft</button></div>
    </details>}
    {message&&<p role="status">{message}</p>}
  </section>;
}
