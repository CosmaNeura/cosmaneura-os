import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {clinicalTeamApi} from './clinical-team-api';
import {CLINICAL_NOTE_LABEL,noteSelection,type ShareSavedNoteInput} from './clinical-team-contract';
import {modelCanonical} from './model-work-request';
import {vendorSha256} from './vendor-contract';
import type {Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const identity={mode:'clerk_jwt' as const,getToken:vi.fn(async()=>'invented-token')};
let body:ShareSavedNoteInput,workspace:Workspace;
const json=(value:unknown,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{
  headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
const receipt=()=>({contract:'clinical-note-share.v1',outcome:'saved',source_entry_id:id(4),source_entry_revision:3,workspace});
beforeEach(async()=>{
  vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
  vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','true');vi.stubGlobal('window',{location:{href:'http://localhost:5173'}});
  identity.getToken.mockClear();
  const content='Invented SOAP: medication list unavailable. Confirm with provider. 界🩺';
  const note={id:id(3),version:1,workspace_revision:2,content,content_hash:await vendorSha256(new TextEncoder().encode(modelCanonical({content}))),
    source_reply_id:null,source_revision:1,source_fingerprint:'a'.repeat(64),sources_changed:false,created_at:'2026-10-20T14:00:00Z',review:null};
  body=noteSelection(note,2,'invented-note-share');
  const snapshot={contract:'clinical-note-team-source.v1',request:body,note:{id:note.id,version:note.version,
    content_hash:note.content_hash,source_fingerprint:note.source_fingerprint,content}};
  workspace={id:id(1),appointment_id:id(2),label:'Invented encounter',revision:3,work_candidates:[],note:{latest:note,history:[note]},entries:[{
    id:id(4),revision:3,kind:'conversation',content:modelCanonical(snapshot),source_label:CLINICAL_NOTE_LABEL,
    origin:'authenticated_human',ticket:null,created_at:'2026-10-20T14:00:00Z'}]};
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();vi.unstubAllEnvs();});
it('shares and resolves the exact metadata with fresh auth, bounded contract headers and no implicit replay',async()=>{
  const fetcher=vi.fn(async(_input:unknown,_options:RequestInit)=>json(receipt()));vi.stubGlobal('fetch',fetcher);
  expect(await clinicalTeamApi.share(identity,id(1),body)).toEqual(receipt());
  expect(await clinicalTeamApi.resolve(identity,id(1),body)).toEqual(receipt());
  expect(fetcher.mock.calls.map(call=>call[0])).toEqual([
    `http://127.0.0.1:8018/workspaces/${id(1)}/note/team-source`,
    `http://127.0.0.1:8018/workspaces/${id(1)}/note/team-source/resolve`]);
  for(const [,options] of fetcher.mock.calls){
    expect(options).toMatchObject({method:'POST',body:JSON.stringify(body),credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'});
    const headers=new Headers(options.headers);expect(headers.get('Authorization')).toBe('Bearer invented-token');
    expect(headers.get('X-Cosmas-Clinical-Team')).toBe('1');expect(headers.get('X-Cosmas-Draft-Recovery')).toBe('2');
    expect(headers.has('X-Actor-Principal-Id')).toBe(false);expect(options.body).not.toContain('Invented SOAP');
  }
  expect(identity.getToken).toHaveBeenCalledTimes(2);expect(identity.getToken).toHaveBeenCalledWith({skipCache:true});
});
it.each(['text','hash','request','workspace','revision','extra'] as const)('withholds a mismatched saved receipt: %s',async fault=>{
  const value=structuredClone(receipt());
  if(fault==='workspace')value.workspace.id=id(99);
  if(fault==='revision')value.source_entry_revision=4;
  if(fault==='extra')Object.assign(value,{delivery_authorized:true});
  if(['text','hash','request'].includes(fault)){
    const snapshot=JSON.parse(value.workspace.entries[0].content);
    if(fault==='text')snapshot.note.content+=' changed';
    if(fault==='hash')snapshot.note.content_hash='b'.repeat(64);
    if(fault==='request')snapshot.request.idempotency_key='another-share-key';
    value.workspace.entries[0].content=modelCanonical(snapshot);
  }
  const fetcher=vi.fn(async()=>json(value));vi.stubGlobal('fetch',fetcher);
  await expect(clinicalTeamApi.share(identity,id(1),body)).rejects.toMatchObject({status:503});
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it.each<Record<string,string>>([{'Cache-Control':'private'},{'Content-Type':'text/plain'},{'Content-Length':'12000001'},{'Content-Length':'1'},{'Content-Encoding':'gzip'}])(
  'withholds an unverified transport response %j',async headers=>{
    const fetcher=vi.fn(async()=>json(receipt(),headers));vi.stubGlobal('fetch',fetcher);
    await expect(clinicalTeamApi.share(identity,id(1),body)).rejects.toMatchObject({status:502});expect(fetcher).toHaveBeenCalledTimes(1);
  });
it('does not adopt private data if the native owner changes while reading the reply',async()=>{
  let current=true;let release!:()=>void;
  const access={...identity,nativeSession:{revision:id(9),isCurrent:()=>current}};
  const stream=new ReadableStream<Uint8Array>({start(controller){release=()=>{
    controller.enqueue(new TextEncoder().encode(JSON.stringify(receipt())));controller.close();};}});
  const fetcher=vi.fn(async()=>new Response(stream,{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
  const result=expect(clinicalTeamApi.share(access,id(1),body)).rejects.toMatchObject({status:401});
  await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledOnce());current=false;release();await result;
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it('times out before a late token can dispatch an uncertain share',async()=>{
  vi.useFakeTimers();let release!:(token:string)=>void;
  const access={mode:'clerk_jwt' as const,getToken:()=>new Promise<string>(resolve=>{release=resolve;})};
  const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  const result=expect(clinicalTeamApi.share(access,id(1),body)).rejects.toMatchObject({status:503});
  await vi.waitFor(()=>expect(release).toBeTypeOf('function'));await vi.advanceTimersByTimeAsync(30001);await result;
  release('late-invented-token');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
});
it('does not retry a lost reply, and rejects malformed retained metadata before credentials',async()=>{
  const fetcher=vi.fn(async()=>{throw new TypeError('synthetic lost reply');});vi.stubGlobal('fetch',fetcher);
  await expect(clinicalTeamApi.share(identity,id(1),body)).rejects.toMatchObject({status:503});expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockClear();identity.getToken.mockClear();
  await expect(clinicalTeamApi.share(identity,id(1),{...body,share_with_team:false} as unknown as ShareSavedNoteInput)).rejects.toMatchObject({status:422});
  expect(fetcher).not.toHaveBeenCalled();expect(identity.getToken).not.toHaveBeenCalled();
});
