import {useLayoutEffect,useMemo,useRef,useState,type RefObject} from 'react';

type FrameOptions={
  active:boolean;
  visible?:boolean;
  owner:object|null;
  scope:string;
  messages:string;
  isCurrent:()=>boolean;
  arrivals?:readonly string[];
  onBottomVisible?:()=>void;
};
type FrameLifetime={owner:object|null;scope:string};

/** Native chat owns its message scroll, never the surrounding document. */
export function useMobileChatFrame({active,visible=true,owner,scope,messages,isCurrent,arrivals=[],onBottomVisible}:FrameOptions):{
  scrollRef:RefObject<HTMLDivElement|null>;
  onScroll:()=>void;
  newMessages:number;
  jumpToLatest:()=>void;
  restoreReadingPosition:(top:number)=>void;
  releaseReadingPosition:()=>void;
}{
  const scrollRef=useRef<HTMLDivElement|null>(null);
  const following=useRef(true);
  const current=useRef(isCurrent);current.current=isCurrent;
  const historyVisible=useRef(visible);historyVisible.current=visible;
  const frameLifetime=useMemo(()=>({owner,scope}),[active,owner,scope]);
  const lifetime=useRef<FrameLifetime|null>(null);
  const restored=useRef<{lifetime:FrameLifetime;top:number;applied:number}|null>(null);
  const ownsFrame=()=>active&&!!owner&&lifetime.current===frameLifetime&&current.current();
  const observed=useRef(new Set(arrivals)),unseen=useRef(new Set<string>()),[newMessages,setNewMessages]=useState(0);
  const bottomVisible=useRef(onBottomVisible);bottomVisible.current=onBottomVisible;
  const arrivalKey=JSON.stringify(arrivals);
  const viewed=()=>{
    const element=scrollRef.current;
    if(!active||!lifetime.current||!current.current()||!historyVisible.current||!element||element.clientHeight<=0||element.scrollHeight-element.clientHeight-element.scrollTop>2)return;
    unseen.current.clear();setNewMessages(0);bottomVisible.current?.();
  };
  const clamped=(element:HTMLElement,top:number)=>Math.max(0,Math.min(top,element.scrollHeight-element.clientHeight));
  const applyRestoredPosition=(element:HTMLElement)=>{
    const position=restored.current;if(!position||position.lifetime!==lifetime.current)return false;
    // The same scroll node is hidden while a source is open. Keep the requested
    // position across that layout and any temporary reduction in scroll range.
    if(historyVisible.current&&element.clientHeight>0){element.scrollTop=clamped(element,position.top);position.applied=element.scrollTop;viewed();}
    return true;
  };
  const restoreReadingPosition=(top:number)=>{
    const element=scrollRef.current;if(!ownsFrame()||!element||!Number.isFinite(top))return;
    following.current=false;restored.current={lifetime:lifetime.current!,top:Math.max(0,top),applied:element.scrollTop};applyRestoredPosition(element);
  };
  const releaseReadingPosition=()=>{
    const element=scrollRef.current;if(!ownsFrame()||!historyVisible.current||!restored.current||!element)return;
    restored.current=null;following.current=element.scrollHeight-element.clientHeight-element.scrollTop<=64;
  };
  const onScroll=()=>{
    const element=scrollRef.current;if(!ownsFrame()||!historyVisible.current)return;
    const position=restored.current;
    if(element&&position?.lifetime===lifetime.current){
      if(element.clientHeight<=0)return;
      // Queued events from our own restore must not opt back into following.
      // A different position means the reader has resumed scrolling.
      if(Math.abs(element.scrollTop-position.applied)<=1||Math.abs(element.scrollTop-clamped(element,position.top))<=1){viewed();return;}
      restored.current=null;
    }
    if(element)following.current=element.scrollHeight-element.clientHeight-element.scrollTop<=64;
    viewed();
  };
  const jumpToLatest=()=>{const element=scrollRef.current;if(!ownsFrame()||!historyVisible.current||!element)return;
    restored.current=null;following.current=true;element.scrollTop=Math.max(0,element.scrollHeight-element.clientHeight);viewed();};
  useLayoutEffect(()=>{
    if(!active||!owner)return;
    const episode=frameLifetime;lifetime.current=episode;restored.current=null;following.current=true;
    observed.current=new Set(arrivals);unseen.current.clear();setNewMessages(0);
    const element=scrollRef.current;if(!element)return;
    const bottom=()=>{
      if(lifetime.current!==episode||!current.current()||!historyVisible.current||applyRestoredPosition(element)||!following.current)return;
      element.scrollTop=Math.max(0,element.scrollHeight-element.clientHeight);
      viewed();
    };
    bottom();
    // The native WK frame is resized by keyboardLayoutGuide. Observe its
    // available message height; do not subtract a second keyboard estimate.
    const observer=typeof ResizeObserver==='function'?new ResizeObserver(bottom):null;
    observer?.observe(element);
    const resume=(event:Event)=>{
      if(event.type==='keydown'){
        const key=event as KeyboardEvent,target=event.target;
        if(key.altKey||key.ctrlKey||key.metaKey||!['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(key.key)||
          target instanceof HTMLElement&&(target.closest('input,textarea,select,[contenteditable=true]')||key.key===' '&&target.closest('button,a')))return;
      }
      releaseReadingPosition();
    };
    // At a clamped edge, user intent may produce no scroll event. Let the next
    // reply follow normally after a wheel, swipe or scrolling key there.
    element.addEventListener('wheel',resume,{passive:true});element.addEventListener('touchmove',resume,{passive:true});element.addEventListener('keydown',resume);
    return()=>{observer?.disconnect();element.removeEventListener('wheel',resume);element.removeEventListener('touchmove',resume);element.removeEventListener('keydown',resume);if(lifetime.current===episode){lifetime.current=null;restored.current=null;}};
  },[active,owner,scope]);
  useLayoutEffect(()=>{
    if(!ownsFrame()||!historyVisible.current)return;
    const element=scrollRef.current;if(element&&applyRestoredPosition(element)||!following.current)return;
    if(element)element.scrollTop=Math.max(0,element.scrollHeight-element.clientHeight);
    viewed();
  },[active,owner,scope,messages,visible]);
  useLayoutEffect(()=>{
    if(!active||!lifetime.current||!current.current())return;
    for(const id of arrivals)if(!observed.current.has(id))unseen.current.add(id);
    observed.current=new Set(arrivals);
    for(const id of unseen.current)if(!observed.current.has(id))unseen.current.delete(id);
    if(following.current||restored.current?.lifetime===lifetime.current)viewed();
    setNewMessages(unseen.current.size);
  },[active,owner,scope,arrivalKey]);
  return {scrollRef,onScroll,newMessages,jumpToLatest,restoreReadingPosition,releaseReadingPosition};
}
