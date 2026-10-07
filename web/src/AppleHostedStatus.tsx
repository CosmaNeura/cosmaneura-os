import type {ReactNode} from 'react';
import './apple-hosted-status.css';

/** Apple welcome and recovery presentation; authentication stays in its caller. */
export function AppleHostedStatus({title,detail,role='alert',children}:{
  title:string;detail:string;role?:'alert'|'status';children?:ReactNode;
}) {
  return <main className="apple-hosted-status">
    <header className="apple-hosted-brand" aria-label="CosmaBot">
      <span className="apple-hosted-mark" aria-hidden="true">✳</span><span>CosmaBot</span>
    </header>
    <section className="apple-hosted-card" role={role} aria-labelledby="apple-hosted-title">
      <p className="apple-hosted-kicker">YOUR PRIVATE PRACTICE WORKSPACE</p>
      <h1 id="apple-hosted-title">{title}</h1>
      <p className="apple-hosted-detail">{detail}</p>
      {children&&<div className="apple-hosted-actions">{children}</div>}
    </section>
    <p className="apple-hosted-footer">Private notes and a team for your practice.</p>
  </main>;
}
