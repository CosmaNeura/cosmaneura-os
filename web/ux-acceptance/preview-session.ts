import type {AuthenticatedWorkspaceIdentity} from '../src/workspace-api';
import {nativeRehearsal} from './native-rehearsal';

// A device preference, never an account credential or a draft.
export const PREVIEW_SIGNED_OUT_KEY='cosmabot-preview-signed-out-v1';
type PreviewIdentity=Extract<AuthenticatedWorkspaceIdentity,{mode:'clerk_jwt'}>;
type Store=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
type Snapshot={open:boolean;identity:PreviewIdentity;storageError:boolean};

/** Only the invented-data entry uses this controller. Real accounts use native/Clerk auth. */
export function createPreviewSession(storage:Store|null,native:boolean){
  const listeners=new Set<()=>void>();
  let active=false,epoch=0;
  const remembered=()=>{if(!storage)throw new Error('Preview storage unavailable');return storage.getItem(PREVIEW_SIGNED_OUT_KEY)===null;};
  let storageError=false;
  try{active=remembered();}catch{storageError=true;}
  function makeIdentity():PreviewIdentity{
    const revision=crypto.randomUUID(),created=++epoch;
    const current=()=>active&&created===epoch;
    return {mode:'clerk_jwt',getToken:async()=>{
      if(!current())return null;
      await Promise.resolve();
      // This extra read also fences an old tab before its storage event arrives.
      try{if(!remembered())return null;}catch{return null;}
      return current()?'invented-ui-rehearsal-token':null;
    },...(native?{nativeSession:{revision,isCurrent:current}}:{})};
  }
  let snapshot:Snapshot={open:active,identity:makeIdentity(),storageError};
  function publish(next:Snapshot){snapshot=next;for(const listener of listeners)listener();}
  function close(persist=true){
    active=false;epoch++;
    let failed=false;
    if(persist)try{if(!storage)throw new Error();storage.setItem(PREVIEW_SIGNED_OUT_KEY,'closed');}catch{failed=true;}
    publish({...snapshot,open:false,storageError:failed});
  }
  function enter(){
    // An explicit action is required; another tab cannot open this closed view.
    if(active)return;
    try{if(!storage)throw new Error();storage.removeItem(PREVIEW_SIGNED_OUT_KEY);if(!remembered())throw new Error();}
    catch{publish({...snapshot,open:false,storageError:true});return;}
    active=true;publish({open:true,identity:makeIdentity(),storageError:false});
  }
  return {getSnapshot:()=>snapshot,subscribe:(listener:()=>void)=>{listeners.add(listener);return()=>{listeners.delete(listener);};},close,enter,
    storageChanged:(key:string|null,value:string|null)=>{if(key===PREVIEW_SIGNED_OUT_KEY&&value!==null||key===null)close(false);}};
}

function localStore():Store|null{try{return window.localStorage;}catch{return null;}}
export const previewSession=createPreviewSession(localStore(),nativeRehearsal(new URL(location.href),window.top===window));
export let identity=previewSession.getSnapshot().identity;
previewSession.subscribe(()=>{identity=previewSession.getSnapshot().identity;});
const onStorage=(event:StorageEvent)=>{if(event.storageArea===localStore())previewSession.storageChanged(event.key,event.newValue);};
window.addEventListener('storage',onStorage);
import.meta.hot?.dispose(()=>{previewSession.close(false);window.removeEventListener('storage',onStorage);});
