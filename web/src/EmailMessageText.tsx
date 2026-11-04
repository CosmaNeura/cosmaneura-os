import {useId,useState} from 'react';
import './email-message-text.css';

/** Key this presentation state by the exact read_id so each new read starts open. */
export function EmailMessageText({content,disabled}:{content:string|null;disabled:boolean}){
  const id=useId(),[expanded,setExpanded]=useState(true);
  const toggle=()=>{
    if(disabled)return;
    setExpanded(value=>!value);
  };
  return <div className="email-message-text">
    <button type="button" disabled={disabled} aria-expanded={expanded} aria-controls={id} onClick={toggle}>
      {expanded?'Hide email text':'Show email text'}
    </button>
    <pre id={id} aria-label="Complete selected email" hidden={!expanded}>{content}</pre>
  </div>;
}
