import {useCallback,useEffect,useRef,useState} from 'react';
import {microsoftConnectionRequest,type MicrosoftAction,type MicrosoftStatus,type MicrosoftStart,type MicrosoftView} from './microsoft-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {useSetupNavigationBusy} from './connection-setup-flow';
import {parseRecordNavigationResult,RECORD_NAVIGATION_EVENT} from './core-record-location';
import {useConnectionReturnCheck} from './use-connection-return-check';
import './microsoft-connection.css';

declare global {interface Window {cosmasMicrosoftNavigation?:{version:1;available:boolean;mode:'trusted-click'}}}
type PrivateState={owner:AuthenticatedWorkspaceIdentity;status:MicrosoftStatus|null;start:MicrosoftStart|null;view:MicrosoftView|null};
const when=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});

export function MicrosoftConnectionPanel({identity,onBusyChange,onAuthenticationLost}:{identity:AuthenticatedWorkspaceIdentity;onBusyChange?:(busy:boolean)=>void;onAuthenticationLost:(error:unknown)=>void}){
  const [data,setData]=useState<PrivateState|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[opening,setOpening]=useState(false);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const [unavailableFor,setUnavailableFor]=useState<AuthenticatedWorkspaceIdentity|null>(null);
  const owner=useRef(identity);owner.current=identity;
  // Hide prior-account values during render, before identity-change effects run.
  const visible=data?.owner===identity?data:null,status=visible?.status,start=visible?.start,view=visible?.view;
  const epoch=useRef(0),pending=useRef<AbortController|null>(null),navigationPending=useRef<string|null>(null);
  const denied=useRef(onAuthenticationLost);denied.current=onAuthenticationLost;
  const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
  const capability=window.cosmasMicrosoftNavigation;
  const nativeReady=!native||capability?.version===1&&capability.available&&capability.mode==='trusted-click';
  useSetupNavigationBusy(busy||opening,onBusyChange);
  useEffect(()=>{
    epoch.current++;pending.current?.abort();pending.current=null;navigationPending.current=null;
    setData(null);setMessage('');setBusy(false);setOpening(false);setUnavailableFor(null);
    return()=>{epoch.current++;pending.current?.abort();pending.current=null;};
  },[identity]);
  const run=useCallback(async(action:MicrosoftAction)=>{
    if(owner.current!==identity)return;
    if(pending.current)return 'busy' as const;
    const current=++epoch.current,controller=new AbortController();pending.current=controller;setBusy(true);setMessage('');
    setData(previous=>previous?.owner===identity?{...previous,start:null,view:null}:null);
    try{
      const result=await microsoftConnectionRequest(identity,action,controller.signal);
      if(epoch.current!==current||owner.current!==identity)return;
      setUnavailableFor(null);
      if('authorization_url' in result){setData({owner:identity,status:null,start:result,view:null});setRequestId(crypto.randomUUID());setMessage('Continue with Microsoft, then return here. Your connection will be checked when you return.');}
      else if('kind' in result)setData(previous=>({owner:identity,status:previous?.owner===identity?previous.status:null,start:null,view:result}));
      else if(result.state==='disconnected'){setData(null);setMessage('Microsoft disconnected from CosmasOS. You can reconnect when ready.');}
      else {setData({owner:identity,status:result,start:null,view:null});return result.state;}
    }catch(error){
      if(epoch.current!==current||owner.current!==identity)return;
      setData(null);
      // Recheck connection state, never replay the failed mailbox/calendar read.
      if((action==='mail'||action==='calendar')&&!(error instanceof WorkspaceApiError&&[401,403,404].includes(error.status))){
        const content=action==='mail'?'Email':'Calendar';
        setMessage(`${content} could not be loaded. Checking your connection…`);
        const recoveryTimer=setTimeout(()=>controller.abort(),10000);
        try{
          const checked=await microsoftConnectionRequest(identity,'status',controller.signal);
          if(epoch.current!==current||owner.current!==identity)return;
          if('state' in checked&&checked.state!=='disconnected'){
            setData({owner:identity,status:checked,start:null,view:null});
            setMessage(checked.state==='connected'?`${content} could not be loaded. Your account is still connected. Try again.`:
              checked.state==='sign_in_required'?`Connect your Microsoft account again to load ${content.toLowerCase()}.`:'Finish Microsoft sign-in, then try again.');
            return;
          }
        }catch(recoveryError){
          if(epoch.current!==current||owner.current!==identity)return;
          error=recoveryError;
        }finally{clearTimeout(recoveryTimer);}
      }
      if(error instanceof WorkspaceApiError&&[401,403].includes(error.status)){setMessage('Sign in to CosmasOS again to continue.');denied.current(error);}
      else if(error instanceof WorkspaceApiError&&error.status===409)setMessage('Microsoft sign-in needs to finish or be renewed. Check your connection, then reconnect if needed.');
      else if(error instanceof WorkspaceApiError&&error.status===404){setUnavailableFor(identity);setMessage('Microsoft email and calendar are not enabled for this practice yet.');}
      else setMessage('The result could not be confirmed. Check your connection before trying again.');
    }finally{if(epoch.current===current&&owner.current===identity){pending.current=null;setBusy(false);}}
  },[identity]);
  useEffect(()=>{void run('status');},[run]);
  const returnCheck=useConnectionReturnCheck(identity,()=>run('status'),last=>setMessage(last==='sign_in_pending'
    ?'CosmaBot has not received the Microsoft sign-in result. Finish in your browser, then check the connection here.'
    :'CosmaBot has not confirmed the Microsoft connection. Check the connection again to see the latest result.'));
  const manual=(action:MicrosoftAction)=>{returnCheck.cancel();void run(action);};
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
  return <section className="core-connection-setup microsoft-connection" aria-label="Microsoft email and calendar">
    <header className="personal-connection-heading"><span className="settings-card-icon" aria-hidden="true">M</span><div><h2>Connect Microsoft</h2><p>Email and the week ahead.</p></div></header>
    <p>Connect your work account to see Outlook email and upcoming calendar events here. Microsoft will ask you to approve access.</p>
    <p className="connection-access-summary">This connection is read-only. It cannot send email, change appointments or update your clinical records.</p>
    {!status?.account&&!start&&unavailableFor!==identity&&<ol className="personal-connection-steps"><li>Choose your Microsoft work or school account.</li><li>Review access on Microsoft’s secure sign-in page.</li><li>Return here to view your inbox or upcoming events.</li></ol>}
    <button disabled={blocked} onClick={()=>manual('status')}>{busy?'Working…':'Check Microsoft connection'}</button>
    {status&&<div className="connection-practice">
      {status.account&&<><h3>{status.account.label}</h3><p>{status.account.email}</p></>}
      <p role="status">{status.state==='connected'?'Microsoft connected.':status.state==='completing_sign_in'?'Completing Microsoft sign-in…':status.state==='sign_in_pending'?'Microsoft sign-in is ready to continue.':'Connect your Microsoft account to continue.'}</p>
    </div>}
    {(!status||status.state!=='completing_sign_in')&&!start&&<button className="team-primary" disabled={blocked||!nativeReady||unavailableFor===identity} onClick={()=>manual('start')}>{status?.state==='connected'?'Reconnect Microsoft':'Connect with Microsoft'}</button>}
    {start&&<p>{native?<button type="button" className="team-primary" disabled={blocked||!nativeReady}
      data-microsoft-connection={blocked?undefined:JSON.stringify({schemaVersion:1,requestId,expectedRevision:native.revision,href:start.authorization_url})}
      onClick={begin}>{opening?'Opening Microsoft…':'Continue with Microsoft'}</button>:
      <a className="team-primary microsoft-continue" href={start.authorization_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={begin} onAuxClick={begin}>Continue with Microsoft</a>}</p>}
    {!nativeReady&&<p>Microsoft connection is unavailable in this app build. Ask your practice administrator for the configured beta build.</p>}
    {status?.state==='connected'&&<div className="microsoft-actions"><button disabled={blocked} onClick={()=>manual('mail')}>Read recent email</button><button disabled={blocked} onClick={()=>manual('calendar')}>View next 7 days</button></div>}
    {(start||status&&status.state!=='sign_in_required')&&<button disabled={blocked} onClick={()=>manual('disconnect')}>{status?.state==='connected'?'Disconnect Microsoft':'Cancel Microsoft connection'}</button>}
    {view&&<section aria-label={view.kind==='mail'?'Recent Outlook email':'Upcoming Outlook events'}>
      <h3>{view.kind==='mail'?'Recent email':'Next 7 days'}</h3><p>{view.account.email} · Checked {when(view.observed_at)}</p>
      {view.items.length===0&&<p>{view.kind==='mail'?'Your inbox has no messages.':'No events in the next 7 days.'}</p>}
      <ul className="microsoft-items">{view.kind==='mail'?view.items.map((item,index)=><li key={`${index}:${item.id}`}><strong>{item.subject||'(No subject)'}</strong><span>{item.sender||'Sender unavailable'} · {when(item.received_at)}</span>{!item.is_read&&<small>Unread</small>}</li>):
        view.items.map((item,index)=><li key={`${index}:${item.id}`}><strong>{item.subject||'(Untitled event)'}</strong><span>{when(item.starts_at)} – {when(item.ends_at)}</span>{item.all_day&&<small>All day</small>}{item.cancelled&&<small>Cancelled</small>}</li>)}</ul>
      {view.more&&<p>Showing the first 25. More are available in Outlook.</p>}
    </section>}
    {message&&<p role="status">{message}</p>}
  </section>;
}
