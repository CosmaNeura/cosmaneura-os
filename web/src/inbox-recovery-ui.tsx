import {useEffect,useRef,useState} from 'react';
import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical} from './vendor-contract';
import type {Scope} from './inbox-schema';
import {emptyInboxRecovery,validateInboxRecovery,type InboxRecoveryAccess,type InboxRecoveryRecord} from './inbox-recovery';

export function useInboxRecovery(access:InboxRecoveryAccess|null,scope:Scope){
  const [record,setRecord]=useState(()=>emptyInboxRecovery(scope)),[offer,setOffer]=useState<InboxRecoveryRecord|null>(null);
  const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[denied,setDenied]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState('');
  const [loadFailed,setLoadFailed]=useState(false),[attempt,setAttempt]=useState(0);
  const [saving,setSaving]=useState(false),[saveFailed,setSaveFailed]=useState(false),writes=useRef(0);
  const current=useRef(record),durable=useRef(record),generation=useRef(0),chain=useRef<Promise<unknown>>(Promise.resolve()),running=useRef(false);
  const scopeKey=vendorCanonical(scope);
  const rejectAccess=(failure:unknown)=>{
    if(!(failure instanceof WorkspaceApiError)||![401,403,404].includes(failure.status))return false;
    generation.current++;current.current=emptyInboxRecovery(scope);setRecord(current.current);setOffer(null);setReady(false);setBusy(false);setSaving(false);setSaveFailed(false);setDenied(true);setStatus('');
    setError('Access to private Inbox is unavailable. Sign in and reopen Inbox.');access?.denied?.(failure);return true;
  };
  useEffect(()=>{
    const gen=++generation.current;current.current=emptyInboxRecovery(scope);durable.current=current.current;
    setRecord(current.current);setOffer(null);setReady(false);setBusy(false);setDenied(false);setError('');setStatus('');setLoadFailed(false);
    chain.current=Promise.resolve();running.current=false;writes.current=0;setSaving(false);setSaveFailed(false);
    if(access)void(async()=>{
      await access.authorize();const raw=await access.load();const restored=raw===null?null:await validateInboxRecovery(raw,scope);
      if(gen!==generation.current)return;durable.current=restored??current.current;setOffer(restored);setReady(true);
    })().catch(e=>{if(gen===generation.current&&!rejectAccess(e)){setLoadFailed(true);setError('Private Inbox recovery could not be loaded. Retry loading before making changes.');}});
    return()=>{generation.current++;};
  },[access,scopeKey,attempt]);
  const save=async(value:InboxRecoveryRecord)=>{
    if(!access||!ready||offer||denied)throw Error('Private recovery unavailable');
    const gen=generation.current,snapshot=structuredClone(value);current.current=snapshot;setRecord(snapshot);
    writes.current++;setSaving(true);
    const job=chain.current.then(async()=>{
      if(gen!==generation.current)throw Error('Session changed');
      const checked=await validateInboxRecovery(snapshot,scope);
      if(gen!==generation.current)throw Error('Session changed');
      await access.persist(checked);
      if(gen!==generation.current)throw Error('Session changed');durable.current=checked;
    });chain.current=job;
    try{await job;}catch(e){if(gen===generation.current&&!rejectAccess(e)){
      current.current={...durable.current,drafts:current.current.drafts};setRecord(current.current);setReady(false);setSaveFailed(true);
      setError('Changes could not be saved safely. The previous saved command and receipts are retained. Your edited input remains in this view; retry saving before leaving.');
    }throw e;}finally{if(gen===generation.current){writes.current--;setSaving(writes.current>0);}}
  };
  const run=async(action:()=>Promise<void>)=>{
    if(running.current||!access||!ready||offer||denied)return;
    const gen=generation.current;running.current=true;setBusy(true);setError('');
    try{await chain.current;await access.authorize();if(gen!==generation.current)return;await action();}
    catch(e){if(gen===generation.current&&!rejectAccess(e))setError(previous=>previous||'The Inbox action could not be completed. Your exact saved command and input are retained. Recover its receipt before continuing.');}
    finally{if(gen===generation.current){running.current=false;setBusy(false);}}
  };
  const restore=async()=>{
    if(!offer||!access||running.current||denied)return;
    const gen=generation.current;running.current=true;setBusy(true);
    try{await access.authorize();const checked=await validateInboxRecovery(offer,scope);if(gen!==generation.current)return;
      await access.persist(checked);if(gen!==generation.current)return;
      current.current=checked;durable.current=checked;setRecord(checked);setOffer(null);setStatus('Saved Inbox work restored. Review confirmations are required again. No command was sent.');
    }catch(e){if(gen===generation.current&&!rejectAccess(e))setError('Saved Inbox work could not be restored with current access. Reopen Inbox.');}
    finally{if(gen===generation.current){running.current=false;setBusy(false);}}
  };
  const retrySave=async()=>{
    if(!saveFailed||!access||running.current||denied||saving)return;
    const gen=generation.current;running.current=true;setBusy(true);
    try{await access.authorize();const checked=await validateInboxRecovery(current.current,scope);if(gen!==generation.current)return;
      await access.persist(checked);if(gen!==generation.current)return;
      current.current=checked;durable.current=checked;setRecord(checked);chain.current=Promise.resolve();setSaveFailed(false);setReady(true);setError('');setStatus('Your retained Inbox input is saved. Review confirmations are required before a new action.');
    }catch(e){if(gen===generation.current&&!rejectAccess(e))setError('Retained Inbox input could not be saved yet. Keep this view open and retry when private storage is available.');}
    finally{if(gen===generation.current){running.current=false;setBusy(false);}}
  };
  const unsavedInput=saveFailed&&vendorCanonical(record.drafts)!==vendorCanonical(durable.current.drafts);
  return {record,current,offer,ready,busy,saving,saveFailed,unsavedInput,retrySave,denied,error,status,setStatus,save,run,restore,rejectAccess,loadFailed,
    retryLoad:()=>{if(loadFailed&&!ready&&!busy&&!denied)setAttempt(v=>v+1);},blocked:!ready||!!offer||busy||denied};
}
