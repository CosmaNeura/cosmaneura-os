import {useLayoutEffect,useRef,type RefObject} from 'react';

type FrameOptions={
  active:boolean;
  owner:object|null;
  scope:string;
  messages:string;
  isCurrent:()=>boolean;
};

/** Native chat owns its message scroll, never the surrounding document. */
export function useMobileChatFrame({active,owner,scope,messages,isCurrent}:FrameOptions):{
  scrollRef:RefObject<HTMLDivElement|null>;
  onScroll:()=>void;
}{
  const scrollRef=useRef<HTMLDivElement|null>(null);
  const following=useRef(true);
  const current=useRef(isCurrent);current.current=isCurrent;
  const lifetime=useRef<object|null>(null);
  const onScroll=()=>{
    const element=scrollRef.current;
    if(element)following.current=element.scrollHeight-element.clientHeight-element.scrollTop<=64;
  };
  useLayoutEffect(()=>{
    if(!active||!owner)return;
    const episode={};lifetime.current=episode;following.current=true;
    const element=scrollRef.current;if(!element)return;
    const bottom=()=>{
      if(lifetime.current!==episode||!current.current()||!following.current)return;
      element.scrollTop=Math.max(0,element.scrollHeight-element.clientHeight);
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
  },[active,owner,scope,messages]);
  return {scrollRef,onScroll};
}
