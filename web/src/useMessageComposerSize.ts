import {useLayoutEffect,type RefObject} from 'react';

/** Presentation-only sizing. The existing textarea remains the draft owner. */
export function useMessageComposerSize(ref:RefObject<HTMLTextAreaElement|null>,active:boolean,value:string,scope:string){
  useLayoutEffect(()=>{
    const field=ref.current;if(!active||!field)return;
    // Native content sizing also follows Dynamic Type changes without a render.
    if(typeof CSS!=='undefined'&&CSS.supports?.('field-sizing','content'))return;
    let width=-1;
    const size=()=>{
      const style=getComputedStyle(field),line=parseFloat(style.lineHeight)||parseFloat(style.fontSize)*1.5;
      const padding=(parseFloat(style.paddingTop)||0)+(parseFloat(style.paddingBottom)||0);
      const minimum=Math.max(44,line+padding);
      const maximum=Math.max(minimum,Math.min(line*5+padding,(window.visualViewport?.height??window.innerHeight)*.3));
      field.style.height='auto';field.style.maxHeight=`${maximum}px`;
      field.style.height=`${Math.min(maximum,Math.max(minimum,field.scrollHeight))}px`;
      field.style.overflowY=field.scrollHeight>maximum?'auto':'hidden';
    };
    size();
    const observer=typeof ResizeObserver==='function'?new ResizeObserver(entries=>{
      const next=entries[0]?.contentRect.width;if(next===undefined||next===width)return;width=next;size();
    }):null;
    observer?.observe(field);window.addEventListener('resize',size);window.visualViewport?.addEventListener('resize',size);
    return()=>{observer?.disconnect();window.removeEventListener('resize',size);window.visualViewport?.removeEventListener('resize',size);
      field.style.removeProperty('height');field.style.removeProperty('max-height');field.style.removeProperty('overflow-y');};
  },[ref,active,value,scope]);
}
