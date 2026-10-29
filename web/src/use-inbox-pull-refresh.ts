import {useEffect,useRef,useState} from 'react';
import {subscribeNativeWorkspaceForeground} from './native-workspace-foreground';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

const RELEASE_DISTANCE=88;
type Gesture={id:number;x:number;y:number;claimed:boolean;distance:number};

/** Refresh only a deliberate downward pull at the top of the inbox. Ordinary
 * scrolling, text editing and system edge gestures retain their own behavior. */
export function useInboxPullRefresh({disabled,scope,onRefresh,identity}:{disabled:boolean;scope:string;onRefresh:()=>void|Promise<void>;identity?:AuthenticatedWorkspaceIdentity}){
  const ref=useRef<HTMLElement|null>(null),current=useRef({onRefresh,disabled,scope,identity});current.current={onRefresh,disabled,scope,identity};
  const [distance,setDistance]=useState(0);
  useEffect(()=>{
    setDistance(0);
    const element=ref.current;if(!element||disabled)return;
    let gesture:Gesture|null=null,alive=true,pending=false,nativeVisible=true;
    const allowed=()=>alive&&nativeVisible&&!current.current.disabled&&current.current.scope===scope&&current.current.identity===identity;
    const reset=()=>{gesture=null;setDistance(0);};
    const atTop=()=>{
      for(let parent:HTMLElement|null=element;parent;parent=parent.parentElement)if(parent.scrollTop>1)return false;
      return window.scrollY<=1&&(document.scrollingElement?.scrollTop??0)<=1;
    };
    const start=(event:TouchEvent)=>{
      reset();
      const target=event.target;
      if(!allowed()||pending||document.visibilityState==='hidden'||event.touches.length!==1||!atTop()||!(target instanceof Element)||!element.contains(target)||
        target.closest('input,textarea,select,a,[contenteditable]:not([contenteditable="false"]),[role="dialog"],[role="slider"]'))return;
      const touch=event.touches[0];
      // Leave the system Back/Forward edge swipe untouched.
      if(touch.clientX<24||touch.clientX>window.innerWidth-24)return;
      gesture={id:touch.identifier,x:touch.clientX,y:touch.clientY,claimed:false,distance:0};
    };
    const move=(event:TouchEvent)=>{
      if(!gesture)return;
      if(!allowed()||event.touches.length!==1||event.touches[0].identifier!==gesture.id||!atTop()){reset();return;}
      const touch=event.touches[0],dx=Math.abs(touch.clientX-gesture.x),dy=touch.clientY-gesture.y;
      if(!gesture.claimed){
        if(Math.max(dx,Math.abs(dy))<10)return;
        if(dy<=0||dy<dx*1.4){reset();return;}
      }
      // Never compete with a scroll/gesture the browser has already claimed.
      if(!event.cancelable){reset();return;}
      event.preventDefault();gesture.claimed=true;gesture.distance=Math.max(0,dy);setDistance(gesture.distance);
    };
    const end=(event:TouchEvent)=>{
      const retained=gesture;
      if(!retained)return;
      const released=event.changedTouches.length===1&&event.changedTouches[0].identifier===retained.id&&event.touches.length===0;
      if(retained.claimed&&event.cancelable)event.preventDefault(); // Do not open a row after dragging it.
      reset();
      if(!allowed()||!released||!retained.claimed||retained.distance<RELEASE_DISTANCE||!event.cancelable||!atTop()||pending||document.visibilityState==='hidden')return;
      pending=true;
      // The shared conversations controller owns loading, errors and custody.
      // This gesture adds no alternative request or recovery path.
      const settled=()=>{if(alive)pending=false;};
      try{void Promise.resolve(current.current.onRefresh()).then(settled,settled);}
      catch(cause){pending=false;throw cause;}
    };
    element.addEventListener('touchstart',start,{passive:true});
    element.addEventListener('touchmove',move,{passive:false});
    element.addEventListener('touchend',end,{passive:false});
    element.addEventListener('touchcancel',reset,{passive:true});
    document.addEventListener('visibilitychange',reset);window.addEventListener('blur',reset);
    const removeNative=identity?subscribeNativeWorkspaceForeground(identity,()=>{nativeVisible=true;reset();},()=>{nativeVisible=false;reset();}):undefined;
    return()=>{alive=false;gesture=null;removeNative?.();element.removeEventListener('touchstart',start);element.removeEventListener('touchmove',move);element.removeEventListener('touchend',end);element.removeEventListener('touchcancel',reset);document.removeEventListener('visibilitychange',reset);window.removeEventListener('blur',reset);};
  },[disabled,scope,identity]);
  return {ref,distance:disabled?0:Math.min(64,distance*.5),ready:!disabled&&distance>=RELEASE_DISTANCE};
}
