import {useEffect,useRef,useState} from 'react';
import {coreRecordApi} from './core-record-api';
import {configuredCoreWebOrigin,validCoreWebOrigin,parseRecordNavigationResult,RECORD_NAVIGATION_EVENT,
  RECORD_LOCATION_MAX_AGE_MS,type CoreRecordLocation,type RecordNavigationRequest} from './core-record-location';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import './core-record-link.css';

type CheckedLocation={value:CoreRecordLocation;identity:AuthenticatedWorkspaceIdentity;expiresAfter:number};
const unconfirmed='The browser handoff could not be confirmed. Check your browser before opening again.';

export function CoreRecordLink({identity,workspaceId,locked,onDenied}:{identity:AuthenticatedWorkspaceIdentity;
  workspaceId:string;locked:boolean;onDenied:(error:WorkspaceApiError)=>void}) {
  const [checked,setChecked]=useState<CheckedLocation|null>(null),[attempt,setAttempt]=useState(0);
  const [expired,setExpired]=useState(false),[loading,setLoading]=useState(true),[unavailable,setUnavailable]=useState(false);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID()),[opening,setOpening]=useState(false),[message,setMessage]=useState('');
  const pending=useRef<string|null>(null),denied=useRef(onDenied);denied.current=onDenied;
  const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
  const navigation=window.cosmasCosmaneuraNavigation;
  const nativeReady=!native||navigation?.version===1&&navigation.mode==='trusted-click'&&navigation.available===true;

  useEffect(()=>{
    setChecked(null);setExpired(false);setLoading(true);setUnavailable(false);setMessage('');setOpening(false);pending.current=null;
    if(!validCoreWebOrigin(configuredCoreWebOrigin())||!nativeReady){setLoading(false);setUnavailable(true);return;}
    const controller=new AbortController();
    void coreRecordApi.location(identity,workspaceId,controller.signal).then(value=>{
      if(!controller.signal.aborted){
        const remaining=Math.min(RECORD_LOCATION_MAX_AGE_MS,Date.parse(value.checked_at)+RECORD_LOCATION_MAX_AGE_MS-Date.now());
        setChecked({value,identity,expiresAfter:performance.now()+remaining});setRequestId(crypto.randomUUID());
      }
    }).catch(error=>{
      if(controller.signal.aborted)return;
      setUnavailable(true);
      if(error instanceof WorkspaceApiError&&[401,403].includes(error.status))denied.current(error);
    }).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[identity,workspaceId,attempt,nativeReady]);

  useEffect(()=>{
    if(!checked)return;
    const expire=()=>{
      if(performance.now()>=checked.expiresAfter||Date.now()>=Date.parse(checked.value.checked_at)+RECORD_LOCATION_MAX_AGE_MS)
        setExpired(true);
    };
    const timer=setTimeout(()=>setExpired(true),Math.max(0,checked.expiresAfter-performance.now()));
    window.addEventListener('focus',expire);document.addEventListener('visibilitychange',expire);
    return()=>{clearTimeout(timer);window.removeEventListener('focus',expire);document.removeEventListener('visibilitychange',expire);};
  },[checked]);

  useEffect(()=>{
    const receive=(event:Event)=>{
      if(!pending.current)return;
      const result=parseRecordNavigationResult((event as CustomEvent).detail,pending.current);
      if(!result)return;
      pending.current=null;setOpening(false);setRequestId(crypto.randomUUID());
      setMessage(result.status==='opened'?'Sent to your browser.':unconfirmed);
    };
    document.addEventListener(RECORD_NAVIGATION_EVENT,receive);
    return()=>document.removeEventListener(RECORD_NAVIGATION_EVENT,receive);
  },[]);
  useEffect(()=>{
    if(!opening)return;
    const timer=setTimeout(()=>{pending.current=null;setOpening(false);setRequestId(crypto.randomUUID());setMessage(unconfirmed);},15000);
    return()=>clearTimeout(timer);
  },[opening]);

  const fresh=()=>!!checked&&!expired&&checked.identity===identity&&checked.value.workspace_id===workspaceId&&
    performance.now()<checked.expiresAfter&&Date.now()<Date.parse(checked.value.checked_at)+RECORD_LOCATION_MAX_AGE_MS&&
    Date.parse(checked.value.checked_at)<=Date.now()+5000;
  const ready=fresh()&&!unavailable,blocked=locked||loading||opening||!nativeReady;
  const payload:RecordNavigationRequest|undefined=native&&ready?{schemaVersion:1,requestId,expectedRevision:native.revision,href:checked!.value.href}:undefined;
  const guardBrowser=(event:{preventDefault:()=>void})=>{if(blocked||!fresh()){event.preventDefault();if(!fresh())setExpired(true);}};

  return <div className="core-record-link">
    {ready?(native?<button type="button" disabled={blocked}
      data-cosmaneura-record-link={blocked?undefined:JSON.stringify(payload)} onClick={event=>{
        if(blocked||!fresh()||!native.isCurrent()){event.preventDefault();if(!fresh())setExpired(true);return;}
        pending.current=requestId;setOpening(true);setMessage('');
      }}>{opening?'Opening Cosmaneura…':'Open in Cosmaneura'}<span aria-hidden="true"> ↗</span></button>:
      blocked?<button type="button" disabled>Open in Cosmaneura<span aria-hidden="true"> ↗</span></button>:
      <a href={checked!.value.href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"
        onClick={guardBrowser} onAuxClick={guardBrowser} onContextMenu={guardBrowser}>
        Open in Cosmaneura<span aria-hidden="true"> ↗</span></a>):
      <button type="button" disabled={blocked} onClick={()=>setAttempt(value=>value+1)}>
        {opening?'Opening Cosmaneura…':loading?'Checking Cosmaneura…':checked?'Refresh Cosmaneura link':'Connect to Cosmaneura'}</button>}
    {unavailable&&<small>Cosmaneura is unavailable in this session.</small>}
    {!!message&&<small role="status">{message}</small>}
  </div>;
}
