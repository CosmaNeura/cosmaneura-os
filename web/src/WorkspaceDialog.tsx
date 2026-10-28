import {useEffect,useId,useRef,type ReactNode} from 'react';

export function canFocusWorkspaceControl(element:HTMLElement|null):element is HTMLElement{
  if(!element?.isConnected||element.matches(':disabled')||element.closest('[hidden],[inert],[aria-hidden="true"],[aria-disabled="true"]'))return false;
  for(let node:HTMLElement|null=element;node;node=node.parentElement){const style=getComputedStyle(node);if(style.display==='none'||style.visibility==='hidden'||style.visibility==='collapse')return false;}
  return true;
}

export function WorkspaceDialog({title,onClose,children,closeLabel,canRestoreFocus}:{title:string;onClose:()=>void;children:ReactNode;closeLabel?:string;canRestoreFocus?:()=>boolean}){
  const ref=useRef<HTMLDivElement>(null),id=useId(),close=useRef(onClose);close.current=onClose;
  const opener=useRef(typeof document!=='undefined'&&document.activeElement instanceof HTMLElement?document.activeElement:null);
  useEffect(()=>{
    const previous=opener.current,element=ref.current!;
    const controls=()=>[...element.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]')].filter(canFocusWorkspaceControl);
    let ownsFocus=false;const focused=(event:FocusEvent)=>{ownsFocus=event.target instanceof Node&&element.contains(event.target);};document.addEventListener('focusin',focused);
    (controls()[0]??element).focus();
    ownsFocus=element.contains(document.activeElement);
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();close.current();}
      if(event.key==='Tab'){const items=controls(),first=items[0],last=items.at(-1);
        if(!first){event.preventDefault();element.focus();}
        else if(event.shiftKey&&(document.activeElement===first||document.activeElement===element)){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
    };
    document.addEventListener('keydown',key);
    return()=>{
      document.removeEventListener('keydown',key);document.removeEventListener('focusin',focused);
      const active=document.activeElement,newDialog=[...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')].some(dialog=>dialog!==element&&canFocusWorkspaceControl(dialog));
      // This is the guard from the opening episode, not a later caller's guard.
      // React may remove the focused dialog before passive cleanup (active=body).
      const sameFocus=ownsFocus&&(!active||active===document.body||active===document.documentElement||element.contains(active));
      if(sameFocus&&!newDialog&&(!canRestoreFocus||canRestoreFocus())&&canFocusWorkspaceControl(previous))previous.focus({preventScroll:true});
    };
  },[]);
  return <div className="workspace-dialog-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)onClose();}}>
    <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1} className="workspace-dialog">{closeLabel?<header className="workspace-dialog-heading"><h2 id={id}>{title}</h2><button aria-label={closeLabel} onClick={onClose}>×</button></header>:<h2 id={id}>{title}</h2>}{children}</div>
  </div>;
}
