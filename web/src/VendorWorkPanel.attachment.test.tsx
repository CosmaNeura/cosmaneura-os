import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {VendorWorkPanel} from './VendorWorkPanel';
import {vendorApi} from './vendor-api';
import {artifact,actualOptions} from './vendor-test-fixture';
import {validateVendor,vendorDigest} from './vendor-contract';
import {emptyVendorRecovery,type VendorRecoveryAccess,type VendorRecoveryRecord} from './vendor-recovery';
import type {VendorOperation} from './vendor-operation';
import type {ArtifactResponse} from './vendor-schema';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-token'};
const options=actualOptions();
let root:Root,host:HTMLDivElement,saved:VendorRecoveryRecord,access:VendorRecoveryAccess;
let responses:Map<string,ArtifactResponse>;

async function proof(op:VendorOperation):Promise<ArtifactResponse>{
  if(op.kind!=='artifact_intent'&&op.kind!=='artifact_content')throw new Error('No delivery allowed');
  const r=op.request;
  if(!('artifact_id'in r))throw new Error('Artifact required');
  const source='source'in r?r.source:saved.artifact!.source;
  const fixture=structuredClone(op.kind==='artifact_intent'?artifact.artifact_intent_receipt:artifact.artifact_content_receipt);
  const effect={...fixture.effect,artifact_id:r.artifact_id,receipt_id:crypto.randomUUID()};
  const value={...fixture,scope:op.scope,command_kind:op.kind,idempotency_key:r.idempotency_key,request_sha256:op.request_sha256,effect,
    artifact:{...fixture.artifact,artifact_id:r.artifact_id,source,intent_sha256:'intent_sha256'in r?r.intent_sha256:op.request_sha256,
      document:{artifact_id:r.artifact_id,sha256:r.sha256,byte_length:r.byte_length,media_type:r.media_type}}};
  const {receipt_sha256:_,...unsigned}=effect;
  effect.receipt_sha256=await vendorDigest('cosmas-vendor-public-receipt.v1',{scope:value.scope,command_kind:op.kind,idempotency_key:r.idempotency_key,request_sha256:op.request_sha256,effect:unsigned});
  const checked=validateVendor('ArtifactResponse',value);
  responses.set(op.request_sha256,checked);
  return checked;
}

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);responses=new Map();
  saved=emptyVendorRecovery({kind:'workspace',id:options.workspace_id});
  saved.draft={...saved.draft,action:'srfax_fax',source:options.source,message:'Keep these directions'};
  access={load:vi.fn(async()=>saved),persist:vi.fn(async record=>{saved=structuredClone(record);}),authorize:vi.fn(async()=>{}),denied:vi.fn()};
  vi.spyOn(vendorApi,'options').mockResolvedValue(options);
  vi.spyOn(vendorApi,'catalog').mockResolvedValue({contract_version:1,workspace_id:options.workspace_id,items:[],next_cursor:null,observed_at:options.observed_at});
  vi.spyOn(vendorApi,'execute').mockImplementation(async(_identity,op)=>{
    expect(saved.pending).toEqual(op);return proof(op);
  });
  vi.spyOn(vendorApi,'upload').mockImplementation(async(_identity,op)=>{
    expect(saved.pending).toEqual(op);expect(saved.artifact_write).toEqual(op);
    expect(saved.receipts.some(r=>r.command_kind==='artifact_intent')).toBe(true);
    return proof(op);
  });
  vi.spyOn(vendorApi,'recover').mockImplementation(async(_identity,op)=>responses.get(op.request_sha256)??proof(op));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
const button=(label:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===label)!;
async function until(check:()=>void){
  for(let i=0;i<200;i++){
    let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{/* Await observable state. */}});
    if(done)return;
  }
  check();
}
const idle=()=>until(()=>expect(host.querySelector('[aria-busy="true"]')).toBeNull());
async function click(label:string){await until(()=>expect(button(label)?.matches(':disabled')).toBe(false));await act(async()=>button(label).click());await idle();}
async function mount(){await act(async()=>root.render(<VendorWorkPanel identity={identity} workspaceId={options.workspace_id} recovery={access}/>));await idle();await click('Restore delivery draft');}
async function choose(text='%PDF-1.7\nInvented attachment only\n%%EOF'){
  const bytes=new TextEncoder().encode(text),file=new File([bytes],'invented.pdf',{type:'application/pdf'});
  Object.defineProperty(file,'arrayBuffer',{configurable:true,value:async()=>bytes.buffer});
  const input=host.querySelector<HTMLInputElement>('input[type=file]')!;
  Object.defineProperty(input,'files',{configurable:true,value:[file]});
  await act(async()=>input.dispatchEvent(new Event('change',{bubbles:true})));
  return file;
}

it('attaches a PDF with one click, preserving both durable operations and draft directions',async()=>{
  await mount();const file=await choose();await click('Attach PDF');
  expect(vendorApi.execute).toHaveBeenCalledTimes(1);expect(vi.mocked(vendorApi.execute).mock.calls[0][1].kind).toBe('artifact_intent');
  expect(vendorApi.upload).toHaveBeenCalledTimes(1);expect(vi.mocked(vendorApi.upload).mock.calls[0][2]).toBe(file);
  expect(saved.artifact?.state).toBe('ready');expect(saved.draft.document).toEqual(saved.artifact?.document);
  expect(saved.draft.message).toBe('Keep these directions');expect(button('Preview attached PDF')).toBeTruthy();
  expect(button('Prepare private PDF')).toBeUndefined();expect(button('Use saved PDF')).toBeUndefined();
  expect(saved.receipts.map(r=>r.command_kind)).toEqual(['artifact_intent']);
  expect(saved.pending?.kind).toBe('artifact_content');expect(saved.receipt?.outcome).toBe('recorded');
});

it('stops at a lost intent reply and resumes the same attachment without another intent',async()=>{
  vi.mocked(vendorApi.execute).mockImplementationOnce(async(_identity,op)=>{await proof(op);throw new Error('Reply lost');});
  await mount();await choose();await click('Attach PDF');
  expect(saved.pending?.kind).toBe('artifact_intent');expect(saved.receipt).toBeNull();expect(vendorApi.upload).not.toHaveBeenCalled();
  await click('Recover saved receipt');expect(saved.artifact?.state).toBe('empty');expect(vendorApi.upload).not.toHaveBeenCalled();
  await click('Finish attaching PDF');
  expect(vendorApi.execute).toHaveBeenCalledTimes(1);expect(vendorApi.upload).toHaveBeenCalledTimes(1);
  expect(saved.draft.document).toEqual(saved.artifact?.document);
});

it('recovers a lost upload reply into the draft without uploading twice',async()=>{
  vi.mocked(vendorApi.upload).mockImplementationOnce(async(_identity,op)=>{await proof(op);throw new Error('Reply lost');});
  await mount();await choose();await click('Attach PDF');
  const pending=structuredClone(saved.pending);expect(pending?.kind).toBe('artifact_content');expect(saved.draft.document).toBeNull();
  await click('Recover saved receipt');
  expect(saved.pending).toEqual(pending);expect(saved.draft.document).toEqual(saved.artifact?.document);
  expect(vendorApi.upload).toHaveBeenCalledTimes(1);expect(vendorApi.execute).toHaveBeenCalledTimes(1);
});

it('does not upload when the saved intent receipt cannot be persisted',async()=>{
  vi.mocked(access.persist).mockImplementation(async record=>{
    if(!record)throw new Error('Unexpected journal clear');
    if(record.pending?.kind==='artifact_intent'&&record.receipt?.outcome==='recorded')throw new Error('Disk full');
    saved=structuredClone(record);
  });
  await mount();await choose();await click('Attach PDF');
  expect(vendorApi.execute).toHaveBeenCalledTimes(1);expect(vendorApi.upload).not.toHaveBeenCalled();
  expect(saved.pending?.kind).toBe('artifact_intent');expect(saved.receipt).toBeNull();expect(saved.draft.message).toBe('Keep these directions');
});

it('rejects a different file when continuing a saved attachment',async()=>{
  vi.mocked(vendorApi.execute).mockImplementationOnce(async(_identity,op)=>{await proof(op);throw new Error('Reply lost');});
  await mount();await choose();await click('Attach PDF');await click('Recover saved receipt');
  const existing=structuredClone(saved.artifact);await choose('%PDF-1.7\nA different invented document\n%%EOF');await click('Finish attaching PDF');
  expect(vendorApi.upload).not.toHaveBeenCalled();expect(vendorApi.execute).toHaveBeenCalledTimes(1);
  expect(saved.artifact).toEqual(existing);expect(saved.draft.document).toBeNull();
});

it('discards attachment work when the visit changes while reading the selected file',async()=>{
  await mount();const file=await choose();let release!:(value:ArrayBuffer)=>void;
  Object.defineProperty(file,'arrayBuffer',{configurable:true,value:()=>new Promise<ArrayBuffer>(resolve=>{release=resolve;})});
  await act(async()=>button('Attach PDF').click());await until(()=>expect(release).toBeDefined());
  const changed={...identity,getToken:async()=>'new-session'};
  await act(async()=>root.render(<VendorWorkPanel identity={changed} workspaceId={options.workspace_id} recovery={access}/>));
  await act(async()=>release(new TextEncoder().encode('%PDF-1.7\n%%EOF').buffer));await idle();
  expect(vendorApi.execute).not.toHaveBeenCalled();expect(vendorApi.upload).not.toHaveBeenCalled();expect(saved.artifact).toBeNull();
});

it('does not advance an intent to upload after the account changes during receipt persistence',async()=>{
  let release!:()=>void;
  vi.mocked(access.persist).mockImplementation(async record=>{
    if(record?.pending?.kind==='artifact_intent'&&record.receipt?.outcome==='recorded')await new Promise<void>(resolve=>{release=resolve;});
    if(record)saved=structuredClone(record);
  });
  await mount();await choose();await act(async()=>button('Attach PDF').click());await until(()=>expect(release).toBeDefined());
  const nextAccess:VendorRecoveryAccess={load:vi.fn(async()=>null),persist:vi.fn(async()=>{}),authorize:vi.fn(async()=>{}),denied:vi.fn()};
  await act(async()=>root.render(<VendorWorkPanel identity={{...identity,getToken:async()=>'other-account'}} workspaceId={options.workspace_id} recovery={nextAccess}/>));
  await act(async()=>release());await idle();
  expect(vendorApi.execute).toHaveBeenCalledTimes(1);expect(vendorApi.upload).not.toHaveBeenCalled();
  expect(nextAccess.persist).not.toHaveBeenCalled();expect(saved.draft.document).toBeNull();
});
