import {useId,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import './source-work-reader.css';

/** Switching the chooser changes presentation only; its retained work stays mounted. */
export function SourceWorkReader({className,chooserClassName,contentClassName,chooserLabel,selectedLabel,
  selection,changeLabel,returnLabel,disabled,chooser,children}:{
  className:string;chooserClassName:string;contentClassName:string;chooserLabel:string;selectedLabel:string;
  selection:{key:string;label:string}|null;changeLabel:string;returnLabel:string;disabled:boolean;
  chooser:ReactNode;children:ReactNode;
}){
  const id=useId(),[expandedKey,setExpandedKey]=useState<string|null>(null);
  const expanded=selection===null||expandedKey===selection.key;
  const chooserRef=useRef<HTMLDivElement>(null),contentRef=useRef<HTMLDivElement>(null);
  const focusRequest=useRef<'chooser'|'content'|null>(null),previousSelection=useRef(selection?.key);
  useLayoutEffect(()=>{
    const request=focusRequest.current;focusRequest.current=null;
    // Move focus out of a chooser that just closed after an explicit selection.
    // Background updates never take focus from elsewhere in the app.
    const selectionChanged=previousSelection.current!==selection?.key;
    previousSelection.current=selection?.key;
    if(request==='chooser'&&expanded){
      const selected=chooserRef.current?.querySelector<HTMLButtonElement>('button[data-calendar-event][aria-pressed="true"]:not(:disabled),li button[aria-pressed="true"]:not(:disabled)');
      const first=chooserRef.current?.querySelector<HTMLElement>('input:not(:disabled),button:not(:disabled)');
      (selected??first)?.focus();
    }else if(request==='content'||selectionChanged&&!expanded&&chooserRef.current?.contains(document.activeElement)){
      contentRef.current?.focus();
    }
  },[expanded,selection?.key]);
  const toggle=()=>{
    if(disabled||!selection)return;
    focusRequest.current=expanded?'content':'chooser';
    setExpandedKey(expanded?null:selection.key);
  };
  return <div className={`${className} source-work-reader`} data-chooser-open={expanded}>
    <aside className={`${chooserClassName} source-work-chooser`} aria-label={chooserLabel}>
      {selection&&<div className="source-work-switch">
        <p><span>{selectedLabel}</span><strong>{selection.label}</strong></p>
        <button type="button" disabled={disabled} aria-expanded={expanded} aria-controls={id} onClick={toggle}>
          {expanded?returnLabel:changeLabel}
        </button>
      </div>}
      <div id={id} ref={chooserRef} className="source-work-choices" hidden={!expanded}>{chooser}</div>
    </aside>
    <div className={`${contentClassName} source-work-content`} ref={contentRef} tabIndex={-1}>
      {children}
    </div>
  </div>;
}
