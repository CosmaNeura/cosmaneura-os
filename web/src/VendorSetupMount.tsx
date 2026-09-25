import type {SetupPresentation} from './connection-setup-flow';
import {useContext,useEffect,useMemo,useRef} from 'react';
import {AccountRecoveryContext} from './account-recovery';
import {accountEditorAddress} from './draft-journal';
import {DraftStoreError} from './draft-store';
import {VendorSetupPanel} from './VendorSetupPanel';
import {validateVendorSetupRecovery,type VendorSetupRecoveryAccess} from './vendor-setup-recovery';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';

export const VENDOR_SETUP_BUILD=import.meta.env.VITE_VENDOR_SETUP_ENABLED==='true';

/** Use the existing owner/API-scoped encrypted account journal. No new store. */
export function VendorSetupMount({identity,onDenied,enabled=VENDOR_SETUP_BUILD,presentation='expanded',onBusyChange}:{identity:WorkspaceIdentity;onDenied:(error:unknown)=>void;enabled?:boolean;presentation?:SetupPresentation;onBusyChange?:(blocked:boolean)=>void}){
 const context=useContext(AccountRecoveryContext),denied=useRef(onDenied),live=useRef({identity,context,enabled,active:true,generation:0});
 denied.current=onDenied;
 if(live.current.identity!==identity||live.current.context!==context||live.current.enabled!==enabled)live.current={identity,context,enabled,active:true,generation:live.current.generation+1};
 useEffect(()=>{live.current.active=true;return()=>{live.current.active=false;};},[]);
 const recovery=useMemo<VendorSetupRecoveryAccess|null>(()=>{
  if(!context)return null;
  const generation=live.current.generation;
  const current=()=>live.current.active&&live.current.enabled&&live.current.generation===generation&&live.current.identity===identity&&live.current.context===context;
  const check=()=>{if(!current())throw new WorkspaceApiError(403);};
  const editor='vendor-setup',address=accountEditorAddress(editor);
  return {
   async load(){check();const draft=await context.journal.load(address);check();if(!draft)return null;if(draft.kind!=='account-editor'||draft.editor!==editor||draft.pending!==null)throw new DraftStoreError('integrity');const record=await validateVendorSetupRecovery(draft.data);check();return record;},
   async persist(value){check();if(value){await validateVendorSetupRecovery(value);if(!('mode'in identity)&&(value.scope.box_id!==identity.boxId||value.scope.owner_id!==identity.actorId))throw new WorkspaceApiError(403);}check();await context.journal.persist(address,value?{kind:'account-editor',editor,data:value,pending:null}:null);check();},
   async authorize(){check();await context.authorize();check();},
   denied:error=>{if(current())denied.current(error);},
  };
 },[context,identity,enabled]);
 if(!enabled)return null;
 if(!recovery)return <section aria-label="Messaging and fax connections"><h2>Messaging and fax connections</h2><p role="status">Checking private account access and recovery…</p></section>;
 return <VendorSetupPanel identity={identity} recovery={recovery} enabled presentation={presentation} onBusyChange={onBusyChange}/>;
}
