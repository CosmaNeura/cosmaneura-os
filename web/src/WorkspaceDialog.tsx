import {useEffect,useId,useRef,type ReactNode} from 'react';

export function WorkspaceDialog({title,onClose,children,closeLabel}:{title:string;onClose:()=>void;children:ReactNode;closeLabel?:string}){
  const ref=useRef<HTMLDivElement>(null),id=useId(),close=useRef(onClose);close.current=onClose;
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null,element=ref.current!;
    const controls=()=>[...element.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]')];
    (controls()[0]??element).focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();close.current();}
      if(event.key==='Tab'){const items=controls(),first=items[0],last=items.at(-1);
        if(!first){event.preventDefault();element.focus();}
        else if(event.shiftKey&&(document.activeElement===first||document.activeElement===element)){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
    };
    document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus();};
  },[]);
  return <div className="workspace-dialog-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)onClose();}}>
    <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1} className="workspace-dialog">{closeLabel?<header className="workspace-dialog-heading"><h2 id={id}>{title}</h2><button aria-label={closeLabel} onClick={onClose}>×</button></header>:<h2 id={id}>{title}</h2>}{children}</div>
  </div>;
}
