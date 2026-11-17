import {useCallback,useEffect,useRef,useState} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {WorkspaceApiError} from './workspace-api';
import {
  copyToEhrRemoteApi,
  type CopyToEhrRemoteHighlight,
  type CopyToEhrRemoteSession,
  type CreateCopyToEhrRemoteSession,
} from './copy-to-ehr-remote-api';

export type CopyToEhrRemoteRole='computer'|'phone';
export type CopyToEhrRemoteConnection='idle'|'connecting'|'connected'|'failed'|'ended';

export type UseCopyToEhrRemoteOptions={
  identity:AuthenticatedWorkspaceIdentity;
  enabled:boolean;
  role:CopyToEhrRemoteRole;
  pollMs?:number;
  onHighlight?:(event:CopyToEhrRemoteHighlight)=>void;
};

export type UseCopyToEhrRemoteResult={
  connection:CopyToEhrRemoteConnection;
  session:CopyToEhrRemoteSession|null;
  latestHighlight:CopyToEhrRemoteHighlight|null;
  error:string|null;
  noteNotSent:boolean;
  createSession:(body:CreateCopyToEhrRemoteSession)=>Promise<CopyToEhrRemoteSession|null>;
  joinCurrentSession:()=>Promise<CopyToEhrRemoteSession|null>;
  sendHighlight:(sectionKey:string)=>Promise<boolean>;
  endSession:(reason?:'end'|'logout'|'visit_change')=>Promise<void>;
  clearError:()=>void;
};

const failureMessage='The note was not sent. Use Copy to EHR on this device.';

export function useCopyToEhrRemote(options:UseCopyToEhrRemoteOptions):UseCopyToEhrRemoteResult{
  const {identity,enabled,role,pollMs=1500,onHighlight}=options;
  const [connection,setConnection]=useState<CopyToEhrRemoteConnection>('idle');
  const [session,setSession]=useState<CopyToEhrRemoteSession|null>(null);
  const [latestHighlight,setLatestHighlight]=useState<CopyToEhrRemoteHighlight|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [noteNotSent,setNoteNotSent]=useState(false);
  const live=useRef({identity,enabled,role,onHighlight,sessionId:null as string|null,after:0,alive:true,poll:null as ReturnType<typeof setTimeout>|null});
  live.current.identity=identity;
  live.current.enabled=enabled;
  live.current.role=role;
  live.current.onHighlight=onHighlight;

  const stopPoll=useCallback(()=>{
    if(live.current.poll!==null){
      clearTimeout(live.current.poll);
      live.current.poll=null;
    }
  },[]);

  const fail=useCallback((message=failureMessage)=>{
    stopPoll();
    setConnection('failed');
    setError(message);
    setNoteNotSent(true);
  },[stopPoll]);

  const clearError=useCallback(()=>{
    setError(null);
    setNoteNotSent(false);
  },[]);

  const poll=useCallback(()=>{
    stopPoll();
    const run=async()=>{
      const current=live.current;
      if(!current.alive||!current.enabled||current.role!=='computer'||!current.sessionId)return;
      try{
        const page=await copyToEhrRemoteApi.events(current.identity,current.sessionId,current.after);
        if(!current.alive||current.sessionId!==page.session_id)return;
        setSession(page);
        for(const event of page.events){
          setLatestHighlight(event);
          current.onHighlight?.(event);
        }
        current.after=page.next_after;
        if(page.status!=='open'){
          setConnection('ended');
          stopPoll();
          return;
        }
        setConnection('connected');
        live.current.poll=setTimeout(()=>{void run();},pollMs);
      }catch(caught){
        if(!current.alive)return;
        if(caught instanceof WorkspaceApiError&&(caught.status===404||caught.status===409)){
          setConnection('ended');
          setSession(null);
          stopPoll();
          return;
        }
        fail();
      }
    };
    live.current.poll=setTimeout(()=>{void run();},0);
  },[fail,pollMs,stopPoll]);

  const createSession=useCallback(async(body:CreateCopyToEhrRemoteSession)=>{
    if(!enabled){
      fail('Copy to EHR remote is not available.');
      return null;
    }
    clearError();
    setConnection('connecting');
    try{
      const created=await copyToEhrRemoteApi.create(identity,body);
      live.current.sessionId=created.session_id;
      live.current.after=0;
      setSession(created);
      setLatestHighlight(null);
      setConnection('connected');
      if(role==='computer')poll();
      return created;
    }catch{
      fail();
      return null;
    }
  },[clearError,enabled,fail,identity,poll,role]);

  const joinCurrentSession=useCallback(async()=>{
    if(!enabled){
      fail('Copy to EHR remote is not available.');
      return null;
    }
    clearError();
    setConnection('connecting');
    try{
      const current=await copyToEhrRemoteApi.current(identity);
      live.current.sessionId=current.session_id;
      live.current.after=0;
      setSession(current);
      setConnection('connected');
      return current;
    }catch(caught){
      if(caught instanceof WorkspaceApiError&&caught.status===404){
        setConnection('idle');
        setSession(null);
        setError('No open computer session. Copy to EHR stays on this phone.');
        setNoteNotSent(false);
        return null;
      }
      fail();
      return null;
    }
  },[clearError,enabled,fail,identity]);

  const sendHighlight=useCallback(async(sectionKey:string)=>{
    const current=session;
    if(!enabled||!current||current.status!=='open'){
      fail();
      return false;
    }
    try{
      const event=await copyToEhrRemoteApi.highlight(identity,current.session_id,{
        draft_revision:current.draft_revision,
        section_key:sectionKey,
      });
      setLatestHighlight(event);
      setConnection('connected');
      clearError();
      return true;
    }catch{
      fail();
      return false;
    }
  },[clearError,enabled,fail,identity,session]);

  const endSession=useCallback(async(reason:'end'|'logout'|'visit_change'='end')=>{
    const sessionId=live.current.sessionId??session?.session_id;
    stopPoll();
    if(!sessionId||!enabled){
      setSession(null);
      setConnection('ended');
      return;
    }
    try{
      const ended=await copyToEhrRemoteApi.end(identity,sessionId,reason);
      setSession(ended);
    }catch{
      setSession(null);
    }finally{
      live.current.sessionId=null;
      live.current.after=0;
      setConnection('ended');
    }
  },[enabled,identity,session,stopPoll]);

  useEffect(()=>{
    live.current.alive=true;
    if(!enabled){
      stopPoll();
      setConnection('idle');
      setSession(null);
      live.current.sessionId=null;
    }
    return()=>{
      live.current.alive=false;
      stopPoll();
    };
  },[enabled,identity,role,stopPoll]);

  return {
    connection,
    session,
    latestHighlight,
    error,
    noteNotSent,
    createSession,
    joinCurrentSession,
    sendHighlight,
    endSession,
    clearError,
  };
}
