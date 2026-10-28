import {useEffect,useMemo,useRef,useState} from 'react';
import {VendorWorkPanel} from '../src/VendorWorkPanel';
import {vendorApi} from '../src/vendor-api';
import {artifact,actualOptions} from '../src/vendor-test-fixture';
import {validateVendor,vendorDigest} from '../src/vendor-contract';
import type {VendorRecoveryRecord} from '../src/vendor-recovery';
import type {VendorOperation} from '../src/vendor-operation';
import type {ArtifactResponse} from '../src/vendor-schema';

const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
/** Real attachment UI with invented local receipts; never permits a provider operation. */
export function FaxAttachmentPreview(){
 const saved=useRef<VendorRecoveryRecord|null>(null),[installed,setInstalled]=useState(false),[calls,setCalls]=useState<string[]>([]);
 const options=useMemo(()=>({...actualOptions(),connections:[],correspondences:[]}),[]);
 const access=useMemo(()=>({authorize:async()=>{},load:async()=>saved.current,persist:async(value:VendorRecoveryRecord|null)=>{saved.current=structuredClone(value);}}),[]);
 useEffect(()=>{
  const original={...vendorApi},receipts=new Map<string,ArtifactResponse>();
  const result=async(op:VendorOperation)=>{
   if(!['artifact_intent','artifact_content'].includes(op.kind)||!('artifact_id'in op.request))throw new Error('Only private attachment fixtures are permitted');
   const r=op.request,fixture=structuredClone(op.kind==='artifact_intent'?artifact.artifact_intent_receipt:artifact.artifact_content_receipt);
   const effect={...fixture.effect,artifact_id:r.artifact_id,receipt_id:crypto.randomUUID()};
   const response={...fixture,scope:op.scope,command_kind:op.kind,idempotency_key:r.idempotency_key,request_sha256:op.request_sha256,effect,
    artifact:{...fixture.artifact,artifact_id:r.artifact_id,source:'source'in r?r.source:saved.current!.artifact!.source,intent_sha256:'intent_sha256'in r?r.intent_sha256:op.request_sha256,
     document:{artifact_id:r.artifact_id,sha256:r.sha256,byte_length:r.byte_length,media_type:r.media_type}}};
   const {receipt_sha256:_,...unsigned}=effect;
   effect.receipt_sha256=await vendorDigest('cosmas-vendor-public-receipt.v1',{scope:op.scope,command_kind:op.kind,idempotency_key:r.idempotency_key,request_sha256:op.request_sha256,effect:unsigned});
   const checked=validateVendor('ArtifactResponse',response);receipts.set(op.request_sha256,checked);setCalls(previous=>[...previous,op.kind]);return checked;
  };
  vendorApi.options=async()=>options;
  vendorApi.catalog=async()=>({contract_version:1,workspace_id:options.workspace_id,items:[],next_cursor:null,observed_at:options.observed_at});
  vendorApi.execute=async(_identity,op)=>result(op);
  vendorApi.upload=async(_identity,op)=>result(op);
  vendorApi.recover=async(_identity,op)=>{const found=receipts.get(op.request_sha256);if(!found)throw new Error('Fixture receipt missing');return found;};
  setInstalled(true);return()=>{Object.assign(vendorApi,original);};
 },[options]);
 return <><p role="note">Attachment layout example: choose SRFax and the reviewed note, then attach an invented PDF. No account is connected and no sending action is available.</p>
  {installed&&<VendorWorkPanel identity={identity} workspaceId={options.workspace_id} recovery={access}/>}
  <output aria-label="Attachment fixture calls">{calls.join(', ')||'No attachment calls'}</output></>;
}
