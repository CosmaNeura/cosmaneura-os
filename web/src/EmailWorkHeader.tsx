import './email-work.css';

export type EmailWorkStep='read'|'visit'|'review'|'draft';
const steps:Array<{id:EmailWorkStep;label:string}>=[
  {id:'read',label:'Read'},
  {id:'visit',label:'Choose visit'},
  {id:'review',label:'Review'},
  {id:'draft',label:'Draft reply'},
];

export function EmailWorkHeader({provider,step}:{provider:'Gmail'|'Outlook';step:EmailWorkStep}){
  const current=steps.findIndex(item=>item.id===step);
  return <header className="email-work-header">
    <div className="email-work-heading"><h3 tabIndex={-1}>Work with email</h3><span className="email-work-provider">{provider}</span></div>
    <p>Review an email for the visit, then prepare a reply with Chief.</p>
    <ol className="email-work-steps" aria-label="Email work steps">
      {steps.map((item,index)=><li key={item.id} aria-current={index===current?'step':undefined} data-complete={index<current}>
        <span className="email-work-step-number" aria-hidden="true">{index<current?'✓':index+1}</span><span>{item.label}</span>
      </li>)}
    </ol>
  </header>;
}
