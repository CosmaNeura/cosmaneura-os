import {useEffect,useRef,useState} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {SchedulingLoginStart} from './scheduling-login-api';
import {parseRecordNavigationResult,RECORD_NAVIGATION_EVENT} from './core-record-location';
import {useSetupNavigationBusy} from './connection-setup-flow';
declare global {interface Window {cosmasSchedulingNavigation?:{version:1;available:boolean;mode:'trusted-click'}}}

export function SchedulingGoogleHandoff({identity,start,disabled=false,onReturn,onMessage,onBusyChange}:{identity:AuthenticatedWorkspaceIdentity;start:SchedulingLoginStart;disabled?:boolean;onReturn:()=>void;onMessage:(text:string)=>void;onBusyChange?:(busy:boolean)=>void}){
 const [requestId,setRequestId]=useState(()=>crypto.randomUUID()),[opening,setOpening]=useState(false),[expired,setExpired]=useState(false);
 const navigation=useRef<string|null>(null),returnPending=useRef(false),scope=useRef(identity);scope.current=identity;
 const callbacks=useRef({onReturn,onMessage});callbacks.current={onReturn,onMessage};
 const native=identity.mode==='desktop_native'?{revision:identity.revision,isCurrent:identity.isCurrent}:identity.nativeSession;
 const capability=window.cosmasSchedulingNavigation;
 const ready=!native||capability?.version===1&&capability.available&&capability.mode==='trusted-click';
 useSetupNavigationBusy(opening,onBusyChange);
 useEffect(()=>{
  setExpired(false);const timer=setTimeout(()=>setExpired(true),Math.max(0,Date.parse(start.expires_at)-Date.now()));
  return()=>clearTimeout(timer);
 },[start]);
 useEffect(()=>{
  const returned=()=>{if(returnPending.current&&scope.current===identity&&document.visibilityState!=='hidden'){
   returnPending.current=false;navigation.current=null;setOpening(false);callbacks.current.onReturn();
  }};
  const receive=(event:Event)=>{
   if(!navigation.current||scope.current!==identity)return;const result=parseRecordNavigationResult((event as CustomEvent).detail,navigation.current);if(!result)return;
   navigation.current=null;setOpening(false);setRequestId(crypto.randomUUID());if(result.status!=='opened')callbacks.current.onMessage('The browser handoff could not be confirmed. Check your browser before trying again.');
  };
  window.addEventListener('focus',returned);document.addEventListener('visibilitychange',returned);document.addEventListener(RECORD_NAVIGATION_EVENT,receive);
  return()=>{returnPending.current=false;navigation.current=null;window.removeEventListener('focus',returned);document.removeEventListener('visibilitychange',returned);document.removeEventListener(RECORD_NAVIGATION_EVENT,receive);};
 },[identity]);
 useEffect(()=>{if(!opening)return;const timer=setTimeout(()=>{navigation.current=null;setOpening(false);setRequestId(crypto.randomUUID());callbacks.current.onMessage('Complete sign-in in your browser, then check the connection here.');},15000);return()=>clearTimeout(timer);},[opening]);
 function begin(event:{preventDefault:()=>void}){
  if(disabled||opening||expired||Date.parse(start.expires_at)<=Date.now()||scope.current!==identity||native&&!native.isCurrent()){event.preventDefault();return;}
  returnPending.current=true;if(native){navigation.current=requestId;setOpening(true);}
 }
 const blocked=disabled||opening||expired;
 return <div>
  {native?<button type="button" className="team-primary" disabled={blocked||!ready} data-scheduling-sign-in={blocked?undefined:JSON.stringify({schemaVersion:1,requestId,expectedRevision:native.revision,href:start.authorization_url})} onClick={begin}>{opening?'Opening Google…':'Continue with Google'}</button>:
   <a style={{display:'inline-flex',alignItems:'center',minHeight:44}} aria-disabled={blocked} className="team-primary" href={blocked?undefined:start.authorization_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={begin} onAuxClick={begin}>Continue with Google</a>}
  {!ready&&<p>Google sign-in is unavailable in this app build. Ask your practice administrator for the configured beta build.</p>}
  {expired&&<p>That sign-in link expired. Check your connection before starting again.</p>}
 </div>;
}
