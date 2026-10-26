import {useEffect,useId,useLayoutEffect,useRef,useState,type RefObject} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

/** Presentation-local search. Scroll never changes the query or invokes a
 * request. Only the exact authenticated owner/scope can retain this UI state. */
export function useInboxSearch({container,identity,scope}:{container:RefObject<HTMLElement|null>;identity?:AuthenticatedWorkspaceIdentity;scope:string}){
 const [search,setSearch]=useState(''),[away,setAway]=useState(false),[focused,setFocused]=useState(false);
 const input=useRef<HTMLInputElement>(null),id=useId(),requested=useRef(false);
 const owner=useRef({identity,scope});owner.current={identity,scope};
 const compact=away&&!focused&&search.length===0;
 useLayoutEffect(()=>{
  requested.current=false;setSearch('');setAway(false);setFocused(document.activeElement===input.current);
  return()=>{requested.current=false;};
 },[identity,scope]);
 useLayoutEffect(()=>{
  if(requested.current&&!compact){requested.current=false;input.current?.focus({preventScroll:true});}
 },[compact,focused]);
 useEffect(()=>{
  const element=container.current;if(!element)return;
  let alive=true;
  const scroll=(event:Event)=>{
   if(!alive||owner.current.identity!==identity||owner.current.scope!==scope||element.closest('[hidden]')||document.visibilityState==='hidden')return;
   const target=event.target;
   if(target!==window&&target!==document&&!(target instanceof Element&&target.contains(element)))return;
   let distance=Math.max(window.scrollY,document.scrollingElement?.scrollTop??0);
   for(let parent:HTMLElement|null=element;parent;parent=parent.parentElement)distance=Math.max(distance,parent.scrollTop);
   // Hysteresis avoids expanding again when the shorter field changes scroll
   // anchoring. Only returning to the top restores the default expanded state.
   setAway(current=>distance<=1?false:distance>96?true:current);
  };
  window.addEventListener('scroll',scroll,{capture:true,passive:true});
  return()=>{alive=false;window.removeEventListener('scroll',scroll,true);};
 },[container,identity,scope]);
 return {search,setSearch,compact,input,id,onFocus:()=>setFocused(true),onBlur:()=>setFocused(false),open:()=>{requested.current=true;setFocused(true);}};
}
