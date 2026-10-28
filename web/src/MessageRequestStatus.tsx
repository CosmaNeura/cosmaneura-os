import type {AdmissionObservation} from './model-work-request';
import './message-request-status.css';

export type MessageRequestState=AdmissionObservation['state']|'awaiting_confirmation';
export const messageRequestStatusId=(entryId:string)=>`message-request-status-${entryId}`;
const labels:Record<MessageRequestState,string>={
 awaiting_confirmation:'Waiting for confirmation…',
 reserved:'Waiting to start',
 running:'Working on your request…',
 completed:'Response saved',
 failed:'Request failed',
 unknown:'Result not confirmed',
 abandoned:'Request expired before starting',
};

/** Recorded request state only. Neither local transport activity nor elapsed time
 * establishes a model phase, a tool action, or completed clinical work. */
export function MessageRequestStatus({state,id}:{state:MessageRequestState;id:string}){
 return <p id={id} className="message-request-status" data-request-state={state} role="status" aria-live="polite" aria-atomic="true">
  {state==='running'&&<span className="message-request-status-dots" data-running="true" aria-hidden="true"><span/><span/><span/></span>}
  <span>{labels[state]}</span>
 </p>;
}
