import {useEffect,useRef,useState} from 'react';
import type {Scope} from './membership-schema';
import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical as membershipCanonical} from './vendor-contract';
import {emptyMembershipRecovery,persistMembershipRecovery,validateMembershipRecovery,type MembershipRecoveryAccess,type MembershipRecoveryRecord} from './membership-recovery';

export function useMembershipRecovery(access:MembershipRecoveryAccess|null,scope:Scope){
  const [record,setRecord]=useState(()=>emptyMembershipRecovery(scope)),[offer,setOffer]=useState<MembershipRecoveryRecord|null>(null),[ready,setReady]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),[status,setStatus]=useState(''),[denied,setDenied]=useState(false);
  const denial=(error:unknown)=>{if(error instanceof WorkspaceApiError&&[401,403,404].includes(error.status))setDenied(true);};
  const current=useRef(record),durable=useRef(record),chain=useRef<Promise<unknown>>(Promise.resolve()),generation=useRef(0),running=useRef(false);
  const [initializationFailed,setInitializationFailed]=useState(false);
  const scopeKey=membershipCanonical(scope);
  const loadInitial=async(gen:number)=>{
    if(!access)return;running.current=true;setBusy(true);setInitializationFailed(false);setError('');
    try{await access.authorize();if(generation.current!==gen)return;const value=await access.load();const saved=value===null?null:await validateMembershipRecovery(value,scope);if(generation.current!==gen)return;
      durable.current=saved??current.current;setOffer(saved);setReady(true);
    }catch(e){if(generation.current===gen){const lost=e instanceof WorkspaceApiError&&[401,403,404].includes(e.status);denial(e);setInitializationFailed(!lost);setError('Private recovery is unavailable. Retry loading to recheck access and saved work.');access.denied?.(e);}}
    finally{if(generation.current===gen){running.current=false;setBusy(false);}}
  };
  useEffect(()=>{const gen=++generation.current;setReady(false);setOffer(null);setError('');setStatus('');setBusy(false);setDenied(false);running.current=false;current.current=emptyMembershipRecovery(scope);setRecord(current.current);chain.current=Promise.resolve();
    setInitializationFailed(false);
    if(!access)return;
    void loadInitial(gen);
    return()=>{generation.current++;};
  },[access,scopeKey]);
  const retryInitialization=async()=>{if(!initializationFailed||ready||offer||denied||running.current||!access)return;await loadInitial(generation.current);};
  const save=async(next:MembershipRecoveryRecord,{local=false}:{local?:boolean}={})=>{
    if(!access||!ready||offer)throw new Error('Private recovery is not ready.');const gen=generation.current;
    current.current=next;setRecord(next);const prior=chain.current;
    const result=prior.then(async()=>{if(generation.current!==gen)throw new Error('Session changed.');await persistMembershipRecovery(access,next,{local});if(generation.current===gen)durable.current=next;});chain.current=result;
    try{await result;if(generation.current!==gen)throw new Error('Session changed.');}catch(e){if(generation.current===gen){current.current={...durable.current,draft:current.current.draft};setRecord(current.current);denial(e);setError('This draft could not be saved safely. Previous saved commands and receipts are retained. Reopen the encounter before continuing.');setReady(false);access.denied?.(e);}throw e;}
  };
  const run=async(action:()=>Promise<void>)=>{if(running.current||!ready||offer||!access)return;running.current=true;setBusy(true);setError('');const gen=generation.current;
    try{await chain.current;await access.authorize();if(generation.current!==gen)return;await action();}
    catch(e){if(generation.current===gen){denial(e);setError(previous=>previous||'This action could not be completed. Your draft and saved receipts are retained. Check any saved action before trying again.');access.denied?.(e);}}
    finally{if(generation.current===gen){running.current=false;setBusy(false);}}
  };
  const restore=async()=>{if(!offer||!access||running.current)return;const gen=generation.current;running.current=true;setBusy(true);
    try{await access.authorize();const exact=await validateMembershipRecovery(offer,scope);const restored=exact;if(generation.current!==gen)return;await access.persist(restored);if(generation.current!==gen)return;
      current.current=restored;durable.current=restored;setRecord(restored);setOffer(null);setStatus('Private membership draft restored. Review the saved command before retrying. No enrollment, message or payment action has occurred.');
    }catch(error){if(generation.current===gen){denial(error);setError('Access changed before this draft could be restored. Sign in again or reopen this work.');access.denied?.(error);}}
    finally{if(generation.current===gen){running.current=false;setBusy(false);}}
  };
  return {record,current,save,run,offer,restore,ready,busy,error,status,setStatus,denied,initializationFailed,retryInitialization,blocked:!ready||!!offer||busy||denied};
}
export function MembershipRecoveryNotice({state}:{state:ReturnType<typeof useMembershipRecovery>}){return <>
  {state.offer&&<div role="status"><p>A private membership draft is available on this device. Restore it to continue with its exact saved command.</p><button type="button" disabled={state.busy||state.denied} onClick={()=>void state.restore()}>Restore membership draft</button></div>}
  {!state.ready&&!state.error&&<p role="status">Waiting for private recovery…</p>}
  {state.initializationFailed&&!state.denied&&<button type="button" disabled={state.busy} onClick={()=>void state.retryInitialization()}>Retry loading private recovery</button>}
  {state.error&&<p role="alert">{state.error}</p>}{state.status&&<p role="status">{state.status}</p>}
</>;}
