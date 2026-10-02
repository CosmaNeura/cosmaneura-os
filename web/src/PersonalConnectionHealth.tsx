import type {ReactNode} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {connectionServices,useConnectionHealth,type PersonalConnection} from './connection-operation-health';
export const connectionTime=(value:number|string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
export function PersonalConnectionHealth({identity,provider,mailAction,calendarAction}:{identity:AuthenticatedWorkspaceIdentity;provider:PersonalConnection;mailAction:ReactNode;calendarAction?:ReactNode}){
  const health=useConnectionHealth(identity,provider);
  return <div className="personal-connection-health" aria-label={`${provider==='google'?'Google':'Microsoft'} service readiness`}>
    <p className="connection-proof">Email previews show subjects and senders, not the full message. Reading a preview does not mark a patient message reviewed. Calendar reads show event titles and times; they do not book a visit.</p>
    <p className="connection-check-time">Last account check: {health.checkedAt?connectionTime(health.checkedAt):'Not checked'}{!health.accountCurrent&&health.checkedAt?' · Current account unconfirmed':''}</p>
    <div className="connection-service-rows">{connectionServices(provider,health).map(service=><div className="connection-service-row" key={service.kind} data-connection-operation={`${provider}.${service.kind==='mail'?'mail_headers':'calendar_summaries'}`}>
      <div><strong>{service.name}</strong><span className={`connection-badge connection-badge-${service.tone}`}>{service.label}</span>
        <small>{service.detail}</small><small>Last successful read: {service.lastSuccessAt?connectionTime(service.lastSuccessAt):'Not verified in this session'}</small></div>
      <div className="connection-service-action">{service.kind==='mail'?mailAction:calendarAction}</div>
    </div>)}</div>
  </div>;
}
