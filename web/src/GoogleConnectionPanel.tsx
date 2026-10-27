import {useCallback,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {googleConnectionRequest,type GoogleAction,type GoogleStatus,type GoogleStart,type GoogleView} from './google-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {parseRecordNavigationResult,RECORD_NAVIGATION_EVENT} from './core-record-location';
import {useConnectionReturnCheck} from './use-connection-return-check';
import {useGoogleNativeForeground} from './use-google-native-foreground';
import {PersonalConnectionHealth} from './PersonalConnectionHealth';
import {useConnectionHealth,observeConnectionStatus,observeConnectionRead,connectionReadScope,connectionReadFailed,connectionCheckFailed,invalidateConnectionHealth,personalConnectionProgress,type ConnectionReadScope} from './connection-operation-health';
import {EhrReadTask} from './EhrReadTask';
import './microsoft-connection.css';
import './google-connection.css';

declare global {interface Window {cosmasGoogleNavigation?:{version:1;available:boolean;mode:'trusted-click'}}}
type GoogleService='mail'|'calendar';
type GoogleViews={mail?:Extract<GoogleView,{kind:'mail'}>;calendar?:Extract<GoogleView,{kind:'calendar'}>};
type PrivateState={owner:AuthenticatedWorkspaceIdentity;status:GoogleStatus|null;start:GoogleStart|null;views:GoogleViews;scope:ConnectionReadScope|null};
const when=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
function checkedState(identity:AuthenticatedWorkspaceIdentity,previous:PrivateState|null,status:GoogleStatus):PrivateState{
  const scope=connectionReadScope(identity,'google');
  // Retain snapshots only while the exact account, grant version and permissions remain current.
  return {owner:identity,status,start:null,scope,views:scope&&previous?.owner===identity&&previous.scope===scope?previous.views:{}};
}

export type GoogleMessageWorkControls={requestFullMailAccess:()=>void;fullMailAccessBusy:boolean;taskActive:boolean;isTaskCurrent:()=>boolean};
export type GoogleCalendarWorkControls={requestCalendarAccess:()=>void;calendarAccessBusy:boolean;onBusyChange:(busy:boolean)=>void;taskActive:boolean;isTaskCurrent:()=>boolean};
export function GoogleConnectionPanel({identity,onBusyChange,onAuthenticationLost,messageWork,onOpenMessageWork,messageWorkOpen=false,messageWorkLocked=false,onCloseMessageWork,messageWorkReturnLabel='Back to Google connection',onShowConnection,calendarWork,onOpenCalendarWork,calendarWorkLocked=false,calendarWorkOpen=false,onCloseCalendarWork,calendarWorkReturnLabel='Back to Google connection'}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(error:unknown)=>void;
  messageWork?:ReactNode|((controls:GoogleMessageWorkControls)=>ReactNode);onOpenMessageWork?:()=>void;messageWorkOpen?:boolean;messageWorkLocked?:boolean;onCloseMessageWork?:()=>void;messageWorkReturnLabel?:string;onShowConnection?:()=>void;calendarWork?:ReactNode|((controls:GoogleCalendarWorkControls)=>ReactNode);onOpenCalendarWork?:()=>void;calendarWorkLocked?:boolean;calendarWorkOpen?:boolean;onCloseCalendarWork?:()=>void;calendarWorkReturnLabel?:string}){
  const messageTaskHost=useRef<HTMLDivElement>(null),[messageTaskVisible,setMessageTaskVisible]=useState(false);
  const messageTaskCurrent=()=>!!messageTaskHost.current?.isConnected&&!messageTaskHost.current.closest('[hidden]');
  useLayoutEffect(()=>{
    const element=messageTaskHost.current;if(!element){setMessageTaskVisible(false);return;}
    const update=()=>setMessageTaskVisible(messageTaskCurrent());update();
    const observer=new MutationObserver(update);for(let node:HTMLElement|null=element;node;node=node.parentElement)observer.observe(node,{attributes:true,attributeFilter:['hidden']});
    return()=>observer.disconnect();
  },[messageWorkOpen,!!messageWork]);
  const [calendarPending,setCalendarPending]=useState(false);
  const calendarAccountLocked=calendarWorkLocked||calendarPending;
  const calendarTaskHost=useRef<HTMLDivElement>(null),[calendarTaskVisible,setCalendarTaskVisible]=useState(false);
  const calendarTaskCurrent=()=>!!calendarTaskHost.current?.isConnected&&!calendarTaskHost.current.closest('[hidden]');
  useLayoutEffect(()=>{
    const element=calendarTaskHost.current;if(!element){setCalendarTaskVisible(false);return;}
    const update=()=>setCalendarTaskVisible(calendarTaskCurrent());update();
    const observer=new MutationObserver(update);for(let node:HTMLElement|null=element;node;node=node.parentElement)observer.observe(node,{attributes:true,attributeFilter:['hidden']});
    return()=>observer.disconnect();
  },[calendarWorkOpen,!!calendarWork]);
  const [data,setData]=useState<PrivateState|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[opening,setOpening]=useState(false);
  const [service,setService]=useState<GoogleService>('mail');
  const latest=useRef(data);latest.current=data;
  const [action,setAction]=useState<string|null>(null);
  const operation=useRef<{action:GoogleAction;scope:ConnectionReadScope|null}|null>(null);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const [unavailableFor,setUnavailableFor]=useState<AuthenticatedWorkspaceIdentity|null>(null);
  const owner=useRef(identity);owner.current=identity;
  const health=useConnectionHealth(identity,'google');
  // The directory can change this scope while this editor remains mounted and hidden.
  // Withhold old account details and snapshots before the clearing effect runs.
  const [needsCheck,setNeedsCheck]=useState(false);
  const epoch=useRef(0),pending=useRef<AbortController|null>(null),navigationPending=useRef<string|null>(null);
  const denied=useRef(onAuthenticationLost);denied.current=onAuthenticationLost;
  const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
  const capability=window.cosmasGoogleNavigation;
  const nativeReady=!native||capability?.version===1&&capability.available&&capability.mode==='trusted-click';
  useSetupNavigationBusy(opening||busy&&(action==='start'||action==='start_full_mail'||action==='disconnect'),onBusyChange);
  useEffect(()=>{
    epoch.current++;pending.current?.abort();pending.current=null;navigationPending.current=null;
    setData(null);setService('mail');setMessage('');setBusy(false);setAction(null);operation.current=null;setOpening(false);setUnavailableFor(null);
    return()=>{epoch.current++;pending.current?.abort();pending.current=null;invalidateConnectionHealth(identity,'google');};
  },[identity]);
  useEffect(()=>{
    setData(previous=>previous?.owner===identity&&previous.scope!==connectionReadScope(identity,'google')?null:previous);
  },[identity,health.accountVersion,health.accountCurrent]);
  const run=useCallback(async(action:GoogleAction)=>{
    if(owner.current!==identity||!nativeForeground.foreground.current)return;
    if(pending.current)return 'busy' as const;
    const previous=latest.current?.owner===identity?latest.current:null;
    const current=++epoch.current,controller=new AbortController();pending.current=controller;setBusy(true);setAction(action);setMessage('');
    const scope=connectionReadScope(identity,'google');operation.current={action,scope};
    if(action==='start'||action==='start_full_mail'||action==='disconnect')invalidateConnectionHealth(identity,'google');
    setData(previous=>action==='start'||action==='start_full_mail'||action==='disconnect'?null:previous?.owner===identity?{...previous,start:null}:null);
    try{
      const result=await googleConnectionRequest(identity,action,controller.signal);
      if(epoch.current!==current||owner.current!==identity)return;
      setUnavailableFor(null);setNeedsCheck(false);
      if('authorization_url' in result){setData({owner:identity,status:null,start:result,views:{},scope:null});setRequestId(crypto.randomUUID());setMessage('Continue with Google, then return here. Your connection will be checked when you return.');}
      else if('kind' in result){
        if(!observeConnectionRead(identity,'google',scope,result)){invalidateConnectionHealth(identity,'google');setData(null);setMessage('The connected account or its permissions changed. Check your connection before reading again.');return;}
        setData(previous=>({owner:identity,status:previous?.owner===identity?previous.status:null,start:null,scope,
          views:{...(previous?.owner===identity&&previous.scope===scope?previous.views:{}),
            ...(result.kind==='mail'?{mail:result}:{calendar:result})}}));
      }
      else if(result.state==='disconnected'){setData(null);setMessage('Google disconnected from CosmasOS. You can reconnect when ready.');}
      else {observeConnectionStatus(identity,'google',result);setData(checkedState(identity,previous,result));return result.state;}
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
            observeConnectionStatus(identity,'google',recovered);setData(checkedState(identity,previous,recovered));
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
    :'CosmaBot has not confirmed the Google connection. Check the connection again to see the latest result.'),
    identity.mode==='clerk_jwt'&&!!identity.nativeSession);
  const nativeForeground=useGoogleNativeForeground(identity,{
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
  const visible=!nativeForeground.suspended&&!needsCheck&&data?.owner===identity&&data.scope===connectionReadScope(identity,'google')?data:null,
    status=visible?.status,start=visible?.start,view=visible?.views[service];
  const manual=(action:GoogleAction)=>{if(['start','start_full_mail','disconnect'].includes(action)&&(calendarAccountLocked||messageWorkLocked))return;returnCheck.cancel();if(action==='mail'||action==='calendar')setService(action);void run(action);};
  const cancelRead=()=>{
    const active=operation.current;if(!active||active.action==='start'||active.action==='start_full_mail'||active.action==='disconnect')return;
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
    if(busy||opening||calendarAccountLocked||messageWorkLocked||!start||owner.current!==identity||Date.parse(start.expires_at)<=Date.now()||native&&!native.isCurrent()){event.preventDefault();return;}
    returnCheck.begin();
    if(native){navigationPending.current=requestId;setOpening(true);}
  };
  const blocked=busy||opening||nativeForeground.suspended;
  const calendarNeedsPermission=status?.state==='connected'&&status.capabilities?.calendar===false;
  const messageWorkEnabled=import.meta.env.VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED==='true';
  const calendarWorkEnabled=import.meta.env.VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED==='true';
  return <><section className="core-connection-setup microsoft-connection google-connection" aria-label="Google email and calendar" hidden={messageWorkOpen||calendarWorkOpen}>
    <header className="personal-connection-heading"><span className="settings-card-icon" aria-hidden="true">G</span><div><h2>{status?.state==='connected'?'Google Workspace':'Connect Google Workspace'}</h2><p>Email and the week ahead.</p></div></header>
    <p>{status?.state==='connected'?'Your account is connected. Check email and calendar access below.':'Connect your Google account to see recent Gmail headers and your primary calendar here. Google will ask you to approve access.'}</p>
    <p className="connection-access-summary">These connection checks read email headers and event titles and times. {messageWorkEnabled?'Full email work asks for separate access below.':'Message bodies and attachments stay in Gmail.'} CosmaBot cannot send email or change calendar events.</p>
    {nativeForeground.suspended&&<p role="status">Google details are hidden while the app is inactive. Your saved work is retained.</p>}
    {!status?.account&&!start&&unavailableFor!==identity&&<details><summary>How to connect</summary><ol className="personal-connection-steps"><li>Choose your Google account.</li><li>Review access on Google’s secure sign-in page.</li><li>Return here to read recent email.</li></ol></details>}
    <button disabled={blocked} onClick={()=>manual('status')}>Check Google connection</button>
    {busy&&action&&<div className="connection-progress" role="status"><p>{action==='start_full_mail'?'Preparing full email permission…':personalConnectionProgress('google',action)}</p>
      <small>{action==='recovery'?'Account recovery has a 10-second limit. The read will not repeat.':'This request has a 50-second limit.'} {action==='status'||action==='mail'||action==='calendar'||action==='recovery'?'You can keep working elsewhere.':''}</small>
      {action!=='start'&&action!=='start_full_mail'&&action!=='disconnect'&&<button onClick={cancelRead}>Stop waiting</button>}</div>}
    {status&&<div className="connection-practice">
      {status.account&&<><h3>{status.account.label}</h3><p>{status.account.email}</p></>}
      <p role="status">{status.state==='connected'?'Google connected.':status.state==='completing_sign_in'?'Completing Google sign-in…':status.state==='sign_in_pending'?'Google sign-in is ready to continue.':'Connect your Google account to continue.'}</p>
    </div>}
    {(!status||status.state!=='completing_sign_in'&&status.state!=='connected')&&!start&&<button className="team-primary" disabled={blocked||calendarAccountLocked||messageWorkLocked||!nativeReady||unavailableFor===identity} onClick={()=>manual('start')}>Connect with Google</button>}
    {start&&<p>{native?<button type="button" className="team-primary" disabled={blocked||calendarAccountLocked||messageWorkLocked||!nativeReady}
      data-google-connection={blocked||calendarAccountLocked||messageWorkLocked?undefined:JSON.stringify({schemaVersion:1,requestId,expectedRevision:native.revision,href:start.authorization_url})}
      onClick={begin}>{opening?'Opening Google…':'Continue with Google'}</button>:
      <a className="team-primary microsoft-continue" href={blocked||calendarAccountLocked||messageWorkLocked?undefined:start.authorization_url} aria-disabled={blocked||calendarAccountLocked||messageWorkLocked||undefined} tabIndex={blocked||calendarAccountLocked||messageWorkLocked?-1:undefined} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={begin} onAuxClick={begin}>Continue with Google</a>}</p>}
    {!nativeReady&&<p>Google connection is unavailable in this app build. Ask your practice administrator for the configured beta build.</p>}
    {(status?.state==='connected'||status?.state==='sign_in_required')&&<>
      {status.state==='sign_in_required'&&(messageWorkEnabled||calendarWorkEnabled)&&<p>Open saved work to check an unresolved request. Email and calendar contents need current Google access.</p>}
      {calendarWorkEnabled&&onOpenCalendarWork&&<button className="team-primary" disabled={blocked||calendarWorkLocked||messageWorkLocked} onClick={()=>{setService('calendar');onOpenCalendarWork();}}>📅 Work with calendar</button>}
      {messageWorkEnabled&&onOpenMessageWork&&<button className="team-primary" disabled={blocked||messageWorkLocked||calendarAccountLocked} onClick={()=>{setService('mail');onOpenMessageWork();}}>Work with email</button>}
    </>}
    {status?.state==='connected'&&<>
      <div className="google-service-tabs" role="group" aria-label="Choose Google service">
        <button disabled={messageWorkLocked||calendarAccountLocked} aria-pressed={service==='mail'} onClick={()=>setService('mail')}>Email</button>
        <button disabled={messageWorkLocked||calendarAccountLocked} aria-pressed={service==='calendar'} onClick={()=>setService('calendar')}>Calendar</button>
      </div>
      <PersonalConnectionHealth identity={identity} provider="google"
        mailAction={<button className={service==='mail'?'team-primary':undefined} disabled={blocked} onClick={()=>manual('mail')}>{visible?.views.mail?'Refresh email':'Read recent email'}</button>}
        calendarAction={calendarNeedsPermission?<button className={service==='calendar'?'team-primary':undefined} disabled={blocked||!nativeReady||messageWorkLocked||calendarAccountLocked} onClick={()=>manual('start')}>Add calendar access</button>:
          <button className={service==='calendar'?'team-primary':undefined} disabled={blocked||messageWorkLocked||calendarAccountLocked} onClick={()=>manual('calendar')}>{visible?.views.calendar?'Refresh calendar':'View next 7 days'}</button>}/>
      {!view&&<p className="google-results-hint">{service==='mail'?'Read recent email to see up to 10 inbox headers.':calendarNeedsPermission?'Choose Add calendar access to view your week.':'View the next 7 days to see event titles and times.'}</p>}
    </>}

    {(start||status&&status.state!=='connected'&&status.state!=='sign_in_required')&&<button disabled={blocked||calendarAccountLocked||messageWorkLocked} onClick={()=>manual('disconnect')}>Cancel Google connection</button>}
    {view?.kind==='mail'&&<section aria-label="Recent Gmail headers">
      <h3>Recent email</h3><p>Email headers · Last loaded {when(view.observed_at)}</p>
      {view.items.length===0&&<p>Your inbox has no messages.</p>}
      <ul className="microsoft-items">{view.items.map((item,index)=><li key={`${index}:${item.id}`}><strong>{item.subject||'(No subject)'}</strong><span>{item.sender||'Sender unavailable'} · {when(item.received_at)}</span>{!item.is_read&&<small>Unread</small>}</li>)}</ul>
      {view.more&&<p>Showing up to 10 messages. More are available in Gmail.</p>}
    </section>}
    {view?.kind==='calendar'&&<section aria-label="Upcoming Google events">
      <h3>Next 7 days</h3><p>Calendar summaries · Last loaded {when(view.observed_at)}</p>
      {view.items.length===0&&<p>No events in the next 7 days.</p>}
      <ul className="microsoft-items">{view.items.map(item=><li key={item.id}><strong>{item.subject||'(Untitled event)'}</strong>
        <span>{item.all_day?new Date(item.starts_at+'T12:00:00Z').toLocaleDateString(undefined,{dateStyle:'medium',timeZone:'UTC'}):when(item.starts_at)+' – '+when(item.ends_at)}</span>
        {item.all_day&&<small>All day</small>}{item.cancelled&&<small>Cancelled</small>}</li>)}</ul>
      {view.more&&<p>Showing up to 25 events. More are available in Google Calendar.</p>}
    </section>}
    {status?.state==='connected'&&<details className="google-account-controls"><summary>Manage Google account</summary>
      <div className="microsoft-actions"><button disabled={blocked||!nativeReady||messageWorkLocked||calendarAccountLocked} onClick={()=>manual('start')}>Reconnect Google</button>
        <button disabled={blocked||messageWorkLocked||calendarAccountLocked} onClick={()=>manual('disconnect')}>Disconnect Google</button></div>
    </details>}
    {message&&<p role="status">{message}</p>}
  </section>{messageWorkEnabled&&messageWork&&<div ref={messageTaskHost} hidden={!messageWorkOpen}><EhrReadTask title="Review Gmail email" open={messageWorkOpen&&messageTaskVisible} context="Choose an email, then review it for the current visit. Your conversation draft stays in place." returnLabel={messageWorkReturnLabel} returnBlocked={blocked||messageWorkLocked||calendarWorkLocked} onReturn={()=>onCloseMessageWork?.()}>
    {(blocked||messageWorkLocked||calendarWorkLocked)&&<p role="status">Wait for the current step to finish, or stop waiting below, before returning. Your saved request stays on this device.</p>}
    {calendarPending&&<p role="status">Review your saved Calendar work before continuing with email. Use Back, then open Calendar to restore or check its saved result.</p>}
    {typeof messageWork==='function'?messageWork({requestFullMailAccess:()=>{if(!blocked&&!messageWorkLocked&&!calendarAccountLocked&&nativeReady){onShowConnection?.();manual('start_full_mail');}},fullMailAccessBusy:blocked||calendarPending,taskActive:messageTaskVisible,isTaskCurrent:messageTaskCurrent}):messageWork}
  </EhrReadTask></div>}{calendarWorkEnabled&&calendarWork&&<div ref={calendarTaskHost} hidden={!calendarWorkOpen}><EhrReadTask title="Review Google Calendar" open={calendarWorkOpen&&calendarTaskVisible} context="Choose an event, then review its saved summary for the current visit. Your conversation draft stays in place." returnLabel={calendarWorkReturnLabel} returnBlocked={blocked||messageWorkLocked||calendarWorkLocked} onReturn={()=>onCloseCalendarWork?.()}>
    {(blocked||messageWorkLocked||calendarWorkLocked)&&<p role="status">Wait for the current step to finish, or stop waiting below, before returning. Your saved request stays on this device.</p>}
    {typeof calendarWork==='function'?calendarWork({requestCalendarAccess:()=>{if(!blocked&&!calendarAccountLocked&&!messageWorkLocked&&nativeReady){onShowConnection?.();setService('calendar');manual('start');}},calendarAccessBusy:blocked,onBusyChange:setCalendarPending,taskActive:calendarTaskVisible,isTaskCurrent:calendarTaskCurrent}):calendarWork}
  </EhrReadTask></div>}</>;
}
