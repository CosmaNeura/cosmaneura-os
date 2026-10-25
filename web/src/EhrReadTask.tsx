import {useEffect,useRef,type ReactNode} from 'react';
import './ehr-read.css';

/** One visit-scoped task host; hiding it never discards its mounted recovery journal. */
export function EhrReadTask({open,context,returnLabel,returnBlocked,onReturn,children,title='Review an appointment'}:{
 title?:string;open:boolean;context:string;returnLabel:string;returnBlocked:boolean;onReturn:()=>void;children:ReactNode;
}){
 const heading=useRef<HTMLHeadingElement>(null);
 useEffect(()=>{if(!open)return;const frame=requestAnimationFrame(()=>{const target=heading.current;if(target&&!target.closest('[hidden]')){target.focus({preventScroll:true});target.scrollIntoView?.({block:'start'});}});return()=>cancelAnimationFrame(frame);},[open]);
 return <section className="ehr-read-task" aria-label={title} hidden={!open}>
  <header><button className="team-subtle" disabled={returnBlocked} onClick={onReturn}><span aria-hidden="true">‹ </span>{returnLabel}</button>
   <h1 ref={heading} tabIndex={-1}>{title}</h1><p>{context}</p></header>
  {children}
 </section>;
}
