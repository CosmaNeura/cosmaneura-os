import {useEffect,useId,useLayoutEffect,useRef,useState,type RefObject} from 'react';
import {subscribeNativeWorkspaceForeground} from './native-workspace-foreground';
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
  let alive=true,nativeVisible=true,tab=false,frame:number|null=null,revision=0;
  const current=()=>alive&&nativeVisible&&element.isConnected&&owner.current.identity===identity&&owner.current.scope===scope&&!element.closest('[hidden]')&&document.visibilityState!=='hidden';
  const cancel=()=>{revision++;tab=false;if(frame!==null){cancelAnimationFrame(frame);frame=null;}};
  const keydown=(event:KeyboardEvent)=>{
   cancel();tab=current()&&event.key==='Tab'&&!event.altKey&&!event.ctrlKey&&!event.metaKey&&event.target instanceof Node&&element.contains(event.target);
  };
  const keyup=(event:KeyboardEvent)=>{if(event.key==='Tab')tab=false;};
  const blur=(event:FocusEvent)=>{if(event.relatedTarget===null)cancel();};
  const focus=(event:FocusEvent)=>{
   const fromTab=tab;cancel(); // Every next focus consumes Tab, including focus outside this inbox.
   const target=event.target;
   if(!fromTab||!current()||!(target instanceof HTMLButtonElement)||!target.matches('.messages-row')||!element.contains(target))return;
   // Native Tab scrolling can align an oversized row behind the sticky tools.
   // Wait for blur/compaction layout, then clear only its leading focus edge.
   // No focus call: programmatic source returns and pointer actions keep their scroll.
   const selected=revision;
   frame=requestAnimationFrame(()=>{
    if(selected!==revision)return;frame=null;
    if(!current()||document.activeElement!==target||!element.contains(target)||!target.isConnected||target.disabled||target.closest('[hidden]'))return;
    const tools=element.querySelector<HTMLElement>('.messages-inbox-tools');if(!tools)return;
    const toolbar=tools.getBoundingClientRect(),row=target.getBoundingClientRect();
    if(toolbar.height<=0||toolbar.bottom<=0||row.height<=0||row.top>=toolbar.bottom+8)return;
    const delta=row.top-toolbar.bottom-8;
    let scrollOwner:HTMLElement|null=target.parentElement;
    while(scrollOwner&&scrollOwner!==document.body&&scrollOwner!==document.documentElement){
     if(/^(auto|scroll|overlay)$/.test(getComputedStyle(scrollOwner).overflowY)&&scrollOwner.scrollHeight>scrollOwner.clientHeight)break;
     scrollOwner=scrollOwner.parentElement;
    }
    if(scrollOwner&&scrollOwner!==document.body&&scrollOwner!==document.documentElement)scrollOwner.scrollTop=Math.max(0,scrollOwner.scrollTop+delta);
    else window.scrollTo({top:Math.max(0,window.scrollY+delta),left:window.scrollX,behavior:'instant'});
   });
  };
  const scroll=(event:Event)=>{
   if(!current())return;
   const target=event.target;
   if(target!==window&&target!==document&&!(target instanceof Element&&target.contains(element)))return;
   let distance=Math.max(window.scrollY,document.scrollingElement?.scrollTop??0);
   for(let parent:HTMLElement|null=element;parent;parent=parent.parentElement)distance=Math.max(distance,parent.scrollTop);
   // Hysteresis avoids expanding again when the shorter field changes scroll
   // anchoring. Only returning to the top restores the default expanded state.
   setAway(current=>distance<=1?false:distance>96?true:current);
  };
  window.addEventListener('scroll',scroll,{capture:true,passive:true});
  const removeNative=identity?subscribeNativeWorkspaceForeground(identity,()=>{nativeVisible=true;cancel();},()=>{nativeVisible=false;cancel();}):undefined;
  document.addEventListener('keydown',keydown,true);document.addEventListener('keyup',keyup,true);
  document.addEventListener('focusin',focus,true);document.addEventListener('focusout',blur,true);window.addEventListener('blur',cancel);
  document.addEventListener('pointerdown',cancel,true);document.addEventListener('touchstart',cancel,{capture:true,passive:true});
  document.addEventListener('wheel',cancel,{capture:true,passive:true});document.addEventListener('visibilitychange',cancel);
  return()=>{
   alive=false;cancel();removeNative?.();window.removeEventListener('scroll',scroll,true);
   document.removeEventListener('keydown',keydown,true);document.removeEventListener('keyup',keyup,true);
   document.removeEventListener('focusin',focus,true);document.removeEventListener('focusout',blur,true);window.removeEventListener('blur',cancel);
   document.removeEventListener('pointerdown',cancel,true);document.removeEventListener('touchstart',cancel,true);
   document.removeEventListener('wheel',cancel,true);document.removeEventListener('visibilitychange',cancel);
  };
 },[container,identity,scope]);
 return {search,setSearch,compact,input,id,onFocus:()=>setFocused(true),onBlur:()=>setFocused(false),open:()=>{requested.current=true;setFocused(true);}};
}
