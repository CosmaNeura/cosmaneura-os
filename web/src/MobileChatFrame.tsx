import {useLayoutEffect,useRef,useState,type RefObject} from 'react';

type FrameOptions={
  active:boolean;
  owner:object|null;
  scope:string;
  messages:string;
  isCurrent:()=>boolean;
  arrivals?:readonly string[];
  onBottomVisible?:()=>void;
};

/** Native chat owns its message scroll, never the surrounding document. */
export function useMobileChatFrame({active,owner,scope,messages,isCurrent,arrivals=[],onBottomVisible}:FrameOptions):{
  scrollRef:RefObject<HTMLDivElement|null>;
  onScroll:()=>void;
  newMessages:number;
  jumpToLatest:()=>void;
}{
  const scrollRef=useRef<HTMLDivElement|null>(null);
  const following=useRef(true);
  const current=useRef(isCurrent);current.current=isCurrent;
  const lifetime=useRef<object|null>(null);
  const observed=useRef(new Set(arrivals)),unseen=useRef(new Set<string>()),[newMessages,setNewMessages]=useState(0);
  const bottomVisible=useRef(onBottomVisible);bottomVisible.current=onBottomVisible;
  const arrivalKey=JSON.stringify(arrivals);
  const viewed=()=>{
    const element=scrollRef.current;
    if(!active||!lifetime.current||!current.current()||!element||element.clientHeight<=0||element.scrollHeight-element.clientHeight-element.scrollTop>2)return;
    unseen.current.clear();setNewMessages(0);bottomVisible.current?.();
  };
  const onScroll=()=>{
    const element=scrollRef.current;
    if(element)following.current=element.scrollHeight-element.clientHeight-element.scrollTop<=64;
    viewed();
  };
  const jumpToLatest=()=>{const element=scrollRef.current;if(!active||!lifetime.current||!current.current()||!element)return;
    following.current=true;element.scrollTop=Math.max(0,element.scrollHeight-element.clientHeight);viewed();};
  useLayoutEffect(()=>{
    if(!active||!owner)return;
    const episode={};lifetime.current=episode;following.current=true;
    observed.current=new Set(arrivals);unseen.current.clear();setNewMessages(0);
    const element=scrollRef.current;if(!element)return;
    const bottom=()=>{
      if(lifetime.current!==episode||!current.current()||!following.current)return;
      element.scrollTop=Math.max(0,element.scrollHeight-element.clientHeight);
      viewed();
    };
    bottom();
    // The native WK frame is resized by keyboardLayoutGuide. Observe its
    // available message height; do not subtract a second keyboard estimate.
    const observer=typeof ResizeObserver==='function'?new ResizeObserver(bottom):null;
    observer?.observe(element);
    return()=>{observer?.disconnect();if(lifetime.current===episode)lifetime.current=null;};
  },[active,owner,scope]);
  useLayoutEffect(()=>{
    if(!active||!lifetime.current||!current.current()||!following.current)return;
    const element=scrollRef.current;
    if(element)element.scrollTop=Math.max(0,element.scrollHeight-element.clientHeight);
    viewed();
  },[active,owner,scope,messages]);
  useLayoutEffect(()=>{
    if(!active||!lifetime.current||!current.current())return;
    for(const id of arrivals)if(!observed.current.has(id))unseen.current.add(id);
    observed.current=new Set(arrivals);
    for(const id of unseen.current)if(!observed.current.has(id))unseen.current.delete(id);
    if(following.current)viewed();
    setNewMessages(unseen.current.size);
  },[active,owner,scope,arrivalKey]);
  return {scrollRef,onScroll,newMessages,jumpToLatest};
}
