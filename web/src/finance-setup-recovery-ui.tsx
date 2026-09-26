import {useEffect,useRef,useState} from 'react';
import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical} from './vendor-contract';
import type {FinanceSetupScope} from './finance-setup-contract';
import {emptyFinanceSetupRecovery,validateFinanceSetupRecovery,type FinanceSetupRecoveryAccess,type FinanceSetupRecoveryRecord} from './finance-setup-recovery';

export function useFinanceSetupRecovery(access:FinanceSetupRecoveryAccess|null,scope:FinanceSetupScope){
  const [record,setRecord]=useState(()=>emptyFinanceSetupRecovery(scope)),[offer,setOffer]=useState<FinanceSetupRecoveryRecord|null>(null);
  const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[denied,setDenied]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState('');
  const [loadFailed,setLoadFailed]=useState(false),[attempt,setAttempt]=useState(0);
  const [saving,setSaving]=useState(false),[saveFailed,setSaveFailed]=useState(false),writes=useRef(0);
  const current=useRef(record),durable=useRef(record),generation=useRef(0),chain=useRef<Promise<unknown>>(Promise.resolve()),running=useRef(false);
  const scopeKey=vendorCanonical(scope);
  const rejectAccess=(failure:unknown)=>{
    if(!(failure instanceof WorkspaceApiError)||![401,403,404].includes(failure.status))return false;
    generation.current++;current.current=emptyFinanceSetupRecovery(scope);setRecord(current.current);setOffer(null);setReady(false);setBusy(false);setSaving(false);setSaveFailed(false);setDenied(true);setStatus('');
    setError('Access to private payment settings is unavailable. Sign in and reopen Connections.');access?.denied?.(failure);return true;
  };
  useEffect(()=>{
    const gen=++generation.current;current.current=emptyFinanceSetupRecovery(scope);durable.current=current.current;
    setRecord(current.current);setOffer(null);setReady(false);setBusy(false);setDenied(false);setError('');setStatus('');setLoadFailed(false);
    chain.current=Promise.resolve();running.current=false;writes.current=0;setSaving(false);setSaveFailed(false);
    if(access)void(async()=>{
      await access.authorize();const raw=await access.load();const restored=raw===null?null:await validateFinanceSetupRecovery(raw,scope);
      if(gen!==generation.current)return;durable.current=restored??current.current;setOffer(restored);setReady(true);
    })().catch(e=>{if(gen===generation.current&&!rejectAccess(e)){setLoadFailed(true);setError('Private payment settings recovery could not be loaded. Retry loading before making changes.');}});
    return()=>{generation.current++;};
  },[access,scopeKey,attempt]);
  const save=async(value:FinanceSetupRecoveryRecord)=>{
    if(!access||!ready||offer||denied)throw Error('Private recovery unavailable');
    const gen=generation.current,snapshot=structuredClone(value);current.current=snapshot;setRecord(snapshot);
    writes.current++;setSaving(true);
    const job=chain.current.then(async()=>{
      if(gen!==generation.current)throw Error('Session changed');
      const checked=await validateFinanceSetupRecovery(snapshot,scope);
      if(gen!==generation.current)throw Error('Session changed');
      await access.persist(checked);
      if(gen!==generation.current)throw Error('Session changed');durable.current=checked;
    });chain.current=job;
    try{await job;}catch(e){if(gen===generation.current&&!rejectAccess(e)){
      current.current={...durable.current,draft:current.current.draft};setRecord(current.current);setReady(false);setSaveFailed(true);
      setError('These changes could not be saved safely. The previous saved command and receipts are retained. Your edited input remains in this view; retry saving before leaving.');
    }throw e;}finally{if(gen===generation.current){writes.current--;setSaving(writes.current>0);}}
  };
  const run=async(action:()=>Promise<void>)=>{
    if(running.current||!access||!ready||offer||denied)return;
    const gen=generation.current;running.current=true;setBusy(true);setError('');
    try{await chain.current;await access.authorize();if(gen!==generation.current)return;await action();}
    catch(e){if(gen===generation.current&&!rejectAccess(e))setError(previous=>previous||'The settings action could not be completed. Your exact saved command and input are retained. Recover its receipt before continuing.');}
    finally{if(gen===generation.current){running.current=false;setBusy(false);}}
  };
  const restore=async()=>{
    if(!offer||!access||running.current||denied)return;
    const gen=generation.current;running.current=true;setBusy(true);
    try{await access.authorize();const checked=await validateFinanceSetupRecovery(offer,scope);if(gen!==generation.current)return;
      await access.persist(checked);if(gen!==generation.current)return;
      current.current=checked;durable.current=checked;setRecord(checked);setOffer(null);setStatus('Saved settings draft restored. Review confirmations are required again. No command was sent.');
    }catch(e){if(gen===generation.current&&!rejectAccess(e))setError('Saved settings draft could not be restored with current access. Retry restoring this draft.');}
    finally{if(gen===generation.current){running.current=false;setBusy(false);}}
  };
  const retrySave=async()=>{
    if(!saveFailed||!access||running.current||denied||saving)return;
    const gen=generation.current;running.current=true;setBusy(true);
    try{await access.authorize();const checked=await validateFinanceSetupRecovery(current.current,scope);if(gen!==generation.current)return;
      await access.persist(checked);if(gen!==generation.current)return;
      current.current=checked;durable.current=checked;setRecord(checked);chain.current=Promise.resolve();setSaveFailed(false);setReady(true);setError('');setStatus('Your retained settings input is saved. Review confirmations are required before a new action.');
    }catch(e){if(gen===generation.current&&!rejectAccess(e))setError('Retained settings input could not be saved yet. Keep this view open and retry when private storage is available.');}
    finally{if(gen===generation.current){running.current=false;setBusy(false);}}
  };
  const unsavedInput=saveFailed&&vendorCanonical(record.draft)!==vendorCanonical(durable.current.draft);
  return {record,current,offer,ready,busy,saving,saveFailed,unsavedInput,retrySave,denied,error,status,setStatus,save,run,restore,rejectAccess,initializationFailed:loadFailed,
    retryInitialization:()=>{if(loadFailed&&!ready&&!busy&&!denied)setAttempt(v=>v+1);},blocked:!ready||!!offer||busy||denied};
}
