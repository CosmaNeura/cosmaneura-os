import {useEffect,useRef} from 'react';
import './connection-setup-flow.css';

export type SetupPresentation='expanded'|'focused';
export type SetupPage='list'|'edit'|'review'|'history'|'control';
/** Callback identity is not an access boundary and must not reset a retained editor. */
export function useSetupNavigationBusy(blocked:boolean,onBusyChange?: (blocked:boolean)=>void){
  const callback=useRef(onBusyChange);callback.current=onBusyChange;
  useEffect(()=>{callback.current?.(blocked);},[blocked]);
  useEffect(()=>()=>{callback.current?.(false);},[]);
}
export function SetupPageHeader({page,title,blocked,onBack}:{page:SetupPage;title:string;blocked:boolean;onBack:()=>void}){
  return <div className="connection-step-heading">{page!=='list'&&<button type="button" disabled={blocked} onClick={onBack}>Back to connections</button>}<h3>{title}</h3></div>;
}
