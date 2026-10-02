import type {InboxDraftSelection} from './inbox-analysis-contract';
import {IncomingBriefNavigation} from './incoming-brief-navigation';
import {hasUnsavedWork} from './unsaved-work';
import {useCallback,useEffect,useRef,useState,type ReactNode} from 'react';
import {InboxMount,INBOX_BUILD} from './InboxMount';
import {InboxHandoffMount,INBOX_HANDOFF_BUILD} from './InboxHandoffMount';
import type {WorkspaceIdentity} from './workspace-api';
import './practice-hub.css';

type View='assigned'|'incoming'|'handoffs';
export function PracticeHub({identity,onDenied,onBusyChange,onDraftInbox,children}:{
  identity:WorkspaceIdentity;onDenied:(cause:unknown)=>void;
  onBusyChange?:(busy:boolean)=>void;onDraftInbox?:(selection:InboxDraftSelection)=>void;children:ReactNode;
}) {
  const [view,setView]=useState<View>('assigned'),[visited,setVisited]=useState({incoming:false,handoffs:false});
  const [locks,setLocks]=useState({incoming:false,handoffs:false});
  const [selectedTicket,setSelectedTicket]=useState<{id:string;request:number}|null>(null);
  const [source,setSource]=useState<{itemId:string;request:number}|null>(null);
  const blocked=locks.incoming||locks.handoffs;
  const live=useRef({identity,locks});live.current={identity,locks};
  const callback=useRef(onBusyChange);callback.current=onBusyChange;
  const reportIncoming=useCallback((busy:boolean)=>{
    if(live.current.identity!==identity||live.current.locks.incoming===busy)return;
    live.current.locks={...live.current.locks,incoming:busy};setLocks(live.current.locks);
  },[identity]);
  const reportHandoffs=useCallback((busy:boolean)=>{
    if(live.current.identity!==identity||live.current.locks.handoffs===busy)return;
    live.current.locks={...live.current.locks,handoffs:busy};setLocks(live.current.locks);
  },[identity]);
  const go=useCallback((next:View)=>{
    if(live.current.identity!==identity||Object.values(live.current.locks).some(Boolean))return;
    setView(next);if(next!=='assigned')setVisited(v=>({...v,[next]:true}));
  },[identity]);
  const openHandoff=useCallback((itemId:string)=>{
    if(!INBOX_HANDOFF_BUILD||live.current.identity!==identity||Object.values(live.current.locks).some(Boolean))return;
    // Selection only. The child reads current source, patient review and authority itself.
    setSelectedTicket(null);setSource(v=>({itemId,request:(v?.request??0)+1}));setVisited(v=>({...v,handoffs:true}));setView('handoffs');
  },[identity]);
  const openTicket=useCallback((id:string)=>{
    if(!INBOX_HANDOFF_BUILD||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id)||live.current.identity!==identity||
      Object.values(live.current.locks).some(Boolean)||hasUnsavedWork())return;
    setSource(null);setSelectedTicket(v=>({id,request:(v?.request??0)+1}));setVisited(v=>({...v,handoffs:true}));setView('handoffs');
  },[identity]);
  const doneHandoff=useCallback(()=>go(INBOX_BUILD?'incoming':'assigned'),[go]);
  useEffect(()=>{setView('assigned');setVisited({incoming:false,handoffs:false});setLocks({incoming:false,handoffs:false});setSource(null);setSelectedTicket(null);},[identity]);
  useEffect(()=>{callback.current?.(blocked);},[blocked,onBusyChange]);
  useEffect(()=>()=>callback.current?.(false),[]);
  if(!INBOX_BUILD&&!INBOX_HANDOFF_BUILD)return <>{children}</>;
  return <section className="practice-hub" aria-label="Practice workspace">
    <nav aria-label="Practice views">
      <button aria-pressed={view==='assigned'} disabled={blocked} onClick={()=>go('assigned')}>Assigned work</button>
      {INBOX_BUILD&&<button aria-pressed={view==='incoming'} disabled={blocked} onClick={()=>go('incoming')}>Incoming messages</button>}
      {INBOX_HANDOFF_BUILD&&<button aria-pressed={view==='handoffs'} disabled={blocked} onClick={()=>go('handoffs')}>Incoming follow-up</button>}
    </nav>
    {blocked&&<p role="status">Save or recover your unfinished edits before leaving this view.</p>}
    <div hidden={view!=='assigned'}>
      <div className="practice-task-cards" aria-label="Start a practice task">
        {INBOX_BUILD&&<button disabled={blocked} onClick={()=>go('incoming')}><span aria-hidden="true">📥</span><span><strong>Review incoming messages</strong><small>Confirm the patient and review the message before choosing a next step.</small></span><span aria-hidden="true">›</span></button>}
        {INBOX_HANDOFF_BUILD&&<button disabled={blocked} onClick={()=>go('handoffs')}><span aria-hidden="true">🤝</span><span><strong>Review incoming follow-up</strong><small>Check who owns the next action and its saved result.</small></span><span aria-hidden="true">›</span></button>}
      </div>
      <IncomingBriefNavigation.Provider value={INBOX_HANDOFF_BUILD?{openTicket,blocked}:null}>{children}</IncomingBriefNavigation.Provider>
    </div>
    {visited.incoming&&<div hidden={view!=='incoming'}><InboxMount identity={identity} onDenied={onDenied} onBusyChange={reportIncoming} onOpenHandoff={INBOX_HANDOFF_BUILD?openHandoff:undefined} onDraftInbox={onDraftInbox}/></div>}
    {visited.handoffs&&<div hidden={view!=='handoffs'}><InboxHandoffMount identity={identity} onDenied={onDenied} onBusyChange={reportHandoffs} sourceItemId={source?.itemId} sourceRequest={source?.request} selectedTicketId={selectedTicket?.id} ticketRequest={selectedTicket?.request} onDone={doneHandoff}/></div>}
  </section>;
}
