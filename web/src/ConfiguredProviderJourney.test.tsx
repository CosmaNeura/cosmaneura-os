import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CapturePanel } from './CapturePanel';
import { EditorRecoveryContext, type EditorRecoveryAccess } from './editor-recovery';
import { DraftJournal } from './draft-journal';
import { IDBFactory } from '../../clients/capture/node_modules/fake-indexeddb';
import { openDraftStore } from './draft-store';
import type { CaptureRuntime } from './capture-runtime';
import type { CaptureFlowSnapshot } from '../../clients/capture/src/flow/controller';
import type { CaptureDraft } from './capture-notes-api';
import type { Workspace } from './workspace-api';
import golden from '../../tests/fixtures/creator_review.json';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');

const workspace='00000000-0000-4000-8000-000000000002', session=golden.waiting.session_id;
const source=golden.ready.working.working_transcript_id;
const ref=(kind:string,last='1')=>`${kind}_${'0'.repeat(25)}${last}`;
const identity={mode:'clerk_jwt' as const,getToken:vi.fn().mockResolvedValue('invented-token')};
let root:Root,node:HTMLDivElement,access:EditorRecoveryAccess,runtime:CaptureRuntime,idb:IDBFactory;
let state:CaptureFlowSnapshot,publish:(state:CaptureFlowSnapshot)=>void;
let accepted:boolean,loseReview:boolean,note:CaptureDraft,selected:CaptureDraft|undefined;
let calls:{path:string;body:any}[];
const button=(name:string)=>[...node.querySelectorAll('button')].find(b=>b.textContent===name)!;
async function settleUntil(predicate:()=>boolean){
  for(let attempt=0;attempt<100;attempt++){
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));});
    if(predicate())return;
  }
  expect(predicate(),node.textContent??'').toBe(true);
}
const click=async(name:string)=>{
  await settleUntil(()=>!!button(name)&&!button(name).disabled);
  await act(async()=>button(name).click());
};
const response=(body:unknown)=>Response.json(body,{headers:{'Cache-Control':'no-store'}});
async function hash(fields:Record<string,string>){
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(Object.entries(fields))));
  return [...new Uint8Array(bytes)].map(n=>n.toString(16).padStart(2,'0')).join('');
}
const display=async()=>act(async()=>root.render(<EditorRecoveryContext.Provider value={access}>
  <CapturePanel workspaceId={workspace} identity={identity} notesEnabled runtimeFactory={async()=>runtime}
    onReviewDraft={draft=>{selected=draft;}}/>
</EditorRecoveryContext.Provider>));

beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
  vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  idb=new IDBFactory();
  node=document.createElement('div');document.body.append(node);root=createRoot(node);
  accepted=false;loseReview=false;selected=undefined;calls=[];
  access={workspaceId:workspace,journal:new DraftJournal(await openDraftStore({scope:'a'.repeat(64),native:false,indexedDB:idb,crypto:webcrypto})),
    authorize:async()=>({id:workspace} as Workspace),denied:vi.fn()};
  note={session_id:session,scribe_source_id:source,source_sha256:'a'.repeat(64),schema_ref:ref('doctor_note_schema'),
    transcript_ref:null,note_ref:null,status:'not_prepared',note_type:'SOAP',fields:null,field_order:null,note_sha256:null,
    created_at:null,review_required:true,reviewed_source:{kind:'reviewed_english',source_version:1,working_transcript_id:source,working_version:2}};
  state={state:'ready',statusCode:'ready',sessionId:session,recordedChunks:0,queuedChunks:0,elapsedSeconds:0,
    remainingBudgetSeconds:900,remainingAuthoritySeconds:900,transcriptionStatus:null,transcript:null};
  runtime={sourceKind:'synthetic',close:vi.fn().mockResolvedValue(undefined),releaseUploadedCapture:vi.fn().mockResolvedValue(undefined),controller:{
    get snapshot(){return state;},subscribe:listener=>{publish=listener;listener(state);return()=>{};},
    startRecording:async()=>{state={...state,state:'recording'};publish(state);},
    stopRecording:async()=>{state={...state,state:'processing',recordedChunks:1};publish(state);},
    resumePendingWork:async()=>{},acknowledgeGap:async()=>{},finishInterruptedCapture:async()=>{},refreshTranscriptionStatus:vi.fn(),
  }};
  vi.stubGlobal('fetch',vi.fn(async(url:string,options:RequestInit)=>{
    const body=JSON.parse(String(options.body)),path=url.split('/').at(-1)!;calls.push({path,body});
    if(path==='admission')return response({status:'prepared',workspace_id:workspace,session_id:session,
      consent_record_id:'00000000-0000-4000-8000-000000000009',configured_capture:{schema_version:'1.0',language_mode:'en-US+es-US'}});
    if(path==='operations'){
      const kind=body.operation.kind;
      if(kind==='decide_translation'){
        accepted=true;if(loseReview){loseReview=false;throw new Error('invented response loss');}
        return response({workspace_id:workspace,session_id:session,operation:kind,
          receipt:{schema_version:'1.0',session_id:session,saved:true,review_id:'00000000-0000-4000-8000-000000000008'}});
      }
      expect(kind).toBe('creator_review');
      return response({workspace_id:workspace,session_id:session,operation:kind,receipt:accepted?golden.ready:golden.waiting});
    }
    expect(path).toBe('notes');const action=body.note.action;let receipt:unknown=note;
    if(action==='templates')receipt={session_id:session,templates:[{schema_ref:note.schema_ref,note_type:'SOAP',field_names:['Plan']}]};
    else if(action==='prepare'||action==='save'){
      const fields=action==='save'?body.note.edit.fields:{Plan:'Invented draft plan.'};
      note={...note,status:'draft',fields,field_order:['Plan'],note_ref:ref('visit_note',action==='save'?'2':'1'),
        transcript_ref:ref('ai_visit_transcript'),note_sha256:await hash(fields),created_at:new Date().toISOString()};receipt=note;
    }
    return response({workspace_id:workspace,session_id:session,action,receipt});
  }));
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();node.remove();vi.unstubAllGlobals();vi.unstubAllEnvs();});

it('connects recording, translation review, Core editing and reopening the saved version',async()=>{
  await display();await click('Open recording');await click('Start synthetic capture');await click('Stop and upload');
  await settleUntil(()=>node.textContent!.includes('No tengo fiebre.'));expect(button('Continue to note')).toBeUndefined();
  await click('Accept English translation');await click('Continue to note');
  expect(runtime.releaseUploadedCapture).toHaveBeenCalledOnce();
  await click('Prepare draft note');await click('Edit draft');
  await act(async()=>{
    const input=node.querySelector<HTMLTextAreaElement>('[aria-label="Draft Plan"]')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'Provider corrected this invented plan.');
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await click('Save draft edits');await click('Use saved draft for review');
  await settleUntil(()=>selected!==undefined);
  expect(selected?.fields?.Plan).toBe('Provider corrected this invented plan.');expect(selected?.reviewed_source?.working_version).toBe(2);
  await act(async()=>root.render(<div/>));await display();await click('Open recording');await click('Continue to note');
  await settleUntil(()=>node.textContent!.includes('Provider corrected this invented plan.'));
  expect(calls.filter(c=>c.path==='notes'&&c.body.note.action==='prepare')).toHaveLength(1);
  expect(runtime.controller.refreshTranscriptionStatus).not.toHaveBeenCalled();
});

it('recovers a lost translation decision after remount with its exact original key',async()=>{
  state={...state,state:'processing'};loseReview=true;
  await display();await click('Open recording');await click('Accept English translation');
  await settleUntil(()=>node.textContent!.includes('save is unconfirmed'));
  await act(async()=>root.render(<div/>));
  access.journal.close();
  access={...access,journal:new DraftJournal(await openDraftStore({scope:'a'.repeat(64),native:false,indexedDB:idb,crypto:webcrypto}))};
  await display();await click('Open recording');await click('Retry the same decision');
  await settleUntil(()=>!!button('Continue to note'));
  const decisions=calls.filter(c=>c.path==='operations'&&c.body.operation.kind==='decide_translation');
  expect(decisions).toHaveLength(2);expect(decisions[0].body).toEqual(decisions[1].body);
});

it('requires an explicit restart after pause and retries an unconfirmed native stop on the same recorder',async()=>{
  runtime.supportsContinuation=true;runtime.sourceKind='microphone';
  const start=vi.spyOn(runtime.controller,'startRecording');
  runtime.controller.pauseRecording=vi.fn(async()=>{
    state={...state,state:'paused',recordedChunks:1,statusCode:'capture_stop_acknowledgement_pending'};publish(state);
    throw Object.assign(new Error('invented lost stop reply'),{code:'capture_stop_acknowledgement_pending'});
  });
  runtime.controller.acknowledgeGap=vi.fn(async()=>{
    state={...state,state:'ready',statusCode:'capture_continuation_ready'};publish(state);
  });
  runtime.controller.finishInterruptedCapture=vi.fn(async()=>{
    state={...state,state:'processing'};publish(state);
  });
  await display();await click('Open recording');await click('Start recording');await click('Pause recording');
  expect(node.textContent).toContain('Audio capture has stopped.');
  await click('Prepare to resume');expect(start).toHaveBeenCalledTimes(1);
  expect(node.textContent).toContain('Press Start recording when you are ready to continue.');
  await click('Start recording');expect(start).toHaveBeenCalledTimes(2);
  await click('Pause recording');await click('Finish this recording');
  expect(runtime.controller.finishInterruptedCapture).toHaveBeenCalledOnce();
  expect(calls.filter(c=>c.path==='admission')).toHaveLength(1);
});

it('offers upload retry without starting another recording',async()=>{
  state={...state,state:'uploading',statusCode:'capture_upload_pending',recordedChunks:1};
  const start=vi.spyOn(runtime.controller,'startRecording');
  runtime.controller.resumePendingWork=vi.fn(async()=>{state={...state,state:'processing'};publish(state);});
  await display();await click('Open recording');await click('Retry saved work');
  expect(runtime.controller.resumePendingWork).toHaveBeenCalledOnce();expect(start).not.toHaveBeenCalled();
  expect(calls.filter(c=>c.path==='admission')).toHaveLength(1);
});
