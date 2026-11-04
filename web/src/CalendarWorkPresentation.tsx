import type {ReactNode} from 'react';

export type CalendarWorkStep='event'|'visit'|'review'|'chief';
type CalendarProvider='Google Calendar'|'Outlook Calendar';

export function CalendarWorkHeader({provider,step,privateNotebook=false}:{provider:CalendarProvider;step:CalendarWorkStep;privateNotebook?:boolean}) {
 const steps:Array<{id:CalendarWorkStep;label:string}>=[
  {id:'event',label:'Choose event'},
  {id:'visit',label:privateNotebook?'Choose notebook':'Choose visit'},
  {id:'review',label:'Review & save'},
  {id:'chief',label:'Ask Chief'},
 ];
 const current=steps.findIndex(item=>item.id===step);
 return <header className="calendar-work-header">
  <div className="calendar-work-heading"><h3>Work with calendar</h3><span>{provider}</span></div>
  <p>{privateNotebook?'Choose a nonclinical event, review it for this private notebook, then prepare a question for Chief. No patient or visit is linked.':'Choose an event, review it for the visit, then ask Chief to prepare work.'}</p>
  <ol className="calendar-work-steps" aria-label="Calendar work steps">
   {steps.map((item,index)=><li key={item.id} aria-current={index===current?'step':undefined} data-complete={index<current}><span aria-hidden="true">{index<current?'✓':index+1}</span>{item.label}</li>)}
  </ol>
 </header>;
}

export function CalendarWorkEmpty({title,children}:{title:string;children:ReactNode}) {
 return <div className="calendar-work-empty" role="status"><h4>{title}</h4><p>{children}</p></div>;
}

export function CalendarWorkSelection({provider,title,when,cancelled,account,source,sourceKey}:{provider:CalendarProvider;title:string;when:string;cancelled:boolean;account:string;source:string;sourceKey:string}) {
 return <>
  <div className="calendar-work-selected-heading"><p className="calendar-work-eyebrow">Selected event · {provider}</p><h4>Selected event: {title||'(Untitled event)'}</h4></div>
  <dl className="calendar-work-event-details">
   <div><dt>When</dt><dd>{when}</dd></div>
   <div><dt>Status</dt><dd>{cancelled?'Cancelled — check the source calendar':'Not marked cancelled'}</dd></div>
   <div><dt>Source account</dt><dd>{account}</dd></div>
  </dl>
  <details className="calendar-work-exact-source" open key={sourceKey}><summary>Review exact calendar source</summary><pre aria-label="Exact selected calendar summary">{source}</pre></details>
 </>;
}
