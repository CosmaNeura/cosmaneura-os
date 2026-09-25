import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {inboxApi} from './inbox-api';
import {actual,inboxFixtureIdentity as identity,inboxFixtureScope as scope,inboxFixtureItem as itemId,inboxFixtureOperation} from './inbox-test-fixture';
import {inboxSourceMetadata,validateInbox} from './inbox-contract';
import {vendorDigest} from './vendor-contract';
import actualOptions from './__fixtures__/inbox/actual-inbox-review-options.json';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const json=(value:unknown,status=200,headers?:Record<string,string>)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',vi.fn());vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
describe('bounded owner-private Inbox transport',()=>{
  it('derives signed owner scope from the catalog without a selected workspace',async()=>{
    const getToken=vi.fn(async()=> 'invented-token');vi.mocked(fetch).mockResolvedValue(json(actual.catalog));
    expect(await inboxApi.catalog({mode:'clerk_jwt',getToken})).toEqual(actual.catalog);
    expect(getToken).toHaveBeenCalledWith({skipCache:true});expect(fetch).toHaveBeenCalledTimes(1);
    const [url,init]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('http://127.0.0.1:8000/inbox');
    expect(new Headers(init?.headers).get('X-Cosmas-Inbox-Contract')).toBe('1');
    expect(init).toMatchObject({method:'GET',credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
  });
  it('validates full immutable history before exposing the current source and local completion',async()=>{
    vi.mocked(fetch).mockImplementation(async url=>json(String(url).endsWith('/history')?actual.history:actual.closed));
    expect(await inboxApi.detail(identity,scope,itemId)).toEqual({detail:actual.closed,history:actual.history});
    expect(vi.mocked(fetch).mock.calls.map(c=>c[0]).sort()).toEqual([`http://127.0.0.1:8000/inbox/${itemId}`,`http://127.0.0.1:8000/inbox/${itemId}/history`]);
  });
  it.each(['review','rejected'] as const)('returns the exact durable %s result and separately recovers it without retry',async kind=>{
    const op=await inboxFixtureOperation(kind),receipt=actual[`${kind}_receipt`];vi.mocked(fetch).mockImplementation(async()=>json(receipt));
    expect(await inboxApi.execute(identity,op)).toEqual(receipt);expect(await inboxApi.recover(identity,op)).toEqual(receipt);
    const calls=vi.mocked(fetch).mock.calls;expect(calls).toHaveLength(2);expect(calls[0][0]).toBe(`http://127.0.0.1:8000/inbox/${itemId}/${op.kind}`);
    expect(JSON.parse(calls[0][1]!.body as string)).toEqual(op.request);expect(calls[1][0]).toBe('http://127.0.0.1:8000/inbox/resolve');
    expect(JSON.parse(calls[1][1]!.body as string)).toEqual({item_id:itemId,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
  });
  it('does not discard a valid not_found recovery response',async()=>{
    const op=await inboxFixtureOperation(),receipt={...actual.review_receipt,outcome:'not_found',effect:null,rejection:null,receipt_id:null,recorded_at:null,receipt_sha256:null};
    vi.mocked(fetch).mockResolvedValue(json(receipt));expect((await inboxApi.recover(identity,op)).outcome).toBe('not_found');expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('binds separately read source content to retained metadata and the exact patient',async()=>{
    const source=validateInbox('Source',actual.closed.source);vi.mocked(fetch).mockImplementation(async()=>json(source));
    expect(await inboxApi.source(identity,scope,itemId,inboxSourceMetadata(source),source.patient_link_id)).toEqual(source);
    await expect(inboxApi.source(identity,scope,itemId,inboxSourceMetadata(source),crypto.randomUUID())).rejects.toMatchObject({status:502});
  });
  it('loads actual matching encounter choices through the bounded private read-only route',async()=>{
    const optionsScope=validateInbox('Scope',actualOptions.scope),owner={boxId:optionsScope.box_id,actorId:optionsScope.owner_id};
    vi.mocked(fetch).mockResolvedValue(json(actualOptions));expect(await inboxApi.reviewOptions(owner,optionsScope,actualOptions.item_id)).toEqual(actualOptions);
    const [url,init]=vi.mocked(fetch).mock.calls[0];expect(url).toBe(`http://127.0.0.1:8000/inbox/${actualOptions.item_id}/review-options`);expect(init?.method).toBe('GET');expect(init?.body).toBeUndefined();
  });
  it.each(['scope','item'] as const)('refuses substituted %s review options after verifying the response digest',async fault=>{
    const expected=validateInbox('Scope',actualOptions.scope),owner={boxId:expected.box_id,actorId:expected.owner_id},options=structuredClone(actualOptions);
    if(fault==='scope')options.scope.owner_id=crypto.randomUUID();else options.item_id=crypto.randomUUID();
    const {options_sha256:_,...body}=options;options.options_sha256=await vendorDigest('cosmas-inbox-review-options.v1',body);
    vi.mocked(fetch).mockResolvedValue(json(options));await expect(inboxApi.reviewOptions(owner,expected,actualOptions.item_id)).rejects.toMatchObject({status:fault==='scope'?403:502});
  });
  it('rejects invalid routes, untrusted origin and another owner before credentials or transport',async()=>{
    const getToken=vi.fn(async()=> 'invented-token');await expect(inboxApi.detail({mode:'clerk_jwt',getToken},scope,'../other')).rejects.toMatchObject({status:502});
    await expect(inboxApi.history(identity,{...scope,owner_id:crypto.randomUUID()},itemId)).rejects.toMatchObject({status:403});
    vi.stubEnv('VITE_API_BASE','https://evil.invalid');await expect(inboxApi.catalog({mode:'clerk_jwt',getToken})).rejects.toMatchObject({status:503});expect(getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it.each([401,403,404,426])('cancels authority-denied %s content without reading private bytes',async status=>{
    const cancel=vi.fn(async()=>{}),read=vi.fn();vi.mocked(fetch).mockResolvedValue({status,body:{cancel,getReader:()=>({read})}} as unknown as Response);
    await expect(inboxApi.catalog(identity)).rejects.toMatchObject({status});expect(cancel).toHaveBeenCalled();expect(read).not.toHaveBeenCalled();
  });
  it.each(['duplicate','invalid_utf8','no_store','wrong_type','wrong_scope'] as const)('fails closed on %s private response',async fault=>{
    const response=fault==='duplicate'?new Response('{"contract_version":1,"contract_version":1}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):fault==='invalid_utf8'?new Response(new Uint8Array([0xff]),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):fault==='no_store'?json(actual.catalog,200,{'Cache-Control':'public'}):fault==='wrong_type'?json(actual.catalog,200,{'Content-Type':'text/html'}):json({...actual.catalog,scope:{...scope,owner_id:crypto.randomUUID()}});
    vi.mocked(fetch).mockResolvedValue(response);await expect(inboxApi.catalog(identity)).rejects.toThrow();
  });
  it.each([['catalog',131072],['detail',65536],['history',2097152],['source',65536],['review_options',131072],['command',8192]] as const)('bounds declared and streamed %s bytes',async(kind,cap)=>{
    const op=await inboxFixtureOperation(),source=validateInbox('Source',actual.closed.source);
    const call=()=>kind==='catalog'?inboxApi.catalog(identity):kind==='detail'?inboxApi.detail(identity,scope,itemId):kind==='history'?inboxApi.history(identity,scope,itemId):kind==='source'?inboxApi.source(identity,scope,itemId,inboxSourceMetadata(source),source.patient_link_id):kind==='review_options'?inboxApi.reviewOptions(identity,scope,itemId):inboxApi.execute(identity,op);
    for(const declared of [true,false]){
      vi.mocked(fetch).mockImplementation(async url=>kind==='detail'&&String(url).endsWith('/history')?json(actual.history):new Response(new Uint8Array(cap+1),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...(declared?{'Content-Length':String(cap+1)}:{})}}));
      await expect(call()).rejects.toMatchObject({status:503});
    }
  });
  it('rejects a partial history and a modified receipt without returning detail',async()=>{
    vi.mocked(fetch).mockImplementation(async url=>json(String(url).endsWith('/history')?{...actual.history,commands:actual.history.commands.slice(1)}:actual.closed));
    await expect(inboxApi.detail(identity,scope,itemId)).rejects.toMatchObject({status:502});
    const op=await inboxFixtureOperation();vi.mocked(fetch).mockResolvedValue(json({...actual.review_receipt,request_sha256:'0'.repeat(64)}));await expect(inboxApi.execute(identity,op)).rejects.toMatchObject({status:502});
  });
  it('exposes only documented closed error codes and caps errors at2KiB',async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json({contract_version:1,error:{code:'inbox_source_changed'}},409));await expect(inboxApi.catalog(identity)).rejects.toMatchObject({status:409,code:'inbox_source_changed'});
    vi.mocked(fetch).mockResolvedValueOnce(json({contract_version:1,error:{code:'private-untrusted-text'}},409));await expect(inboxApi.catalog(identity)).rejects.toMatchObject({status:409,code:undefined});
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new Uint8Array(2049),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));await expect(inboxApi.catalog(identity)).rejects.toMatchObject({status:503});
  });
  it('includes stalled credentials in its deadline and never dispatches a late token',async()=>{
    vi.useFakeTimers();let release!:(v:string)=>void;
    const result=expect(inboxApi.catalog({mode:'clerk_jwt',getToken:()=>new Promise(resolve=>{release=resolve;})})).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(15001);await result;release('late-invented-token');await vi.advanceTimersByTimeAsync(1);expect(fetch).not.toHaveBeenCalled();
  });
  it('bounds an uncooperative body read and never retries or awaits cancellation',async()=>{
    vi.useFakeTimers();const cancel=vi.fn(()=>new Promise(()=>{}));vi.mocked(fetch).mockResolvedValue({status:200,headers:new Headers({'Content-Type':'application/json','Cache-Control':'no-store'}),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel})}} as unknown as Response);
    const result=expect(inboxApi.catalog(identity)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(15001);await result;expect(cancel).toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('honors caller cancellation before I/O',async()=>{
    const controller=new AbortController();controller.abort();await expect(inboxApi.catalog(identity,controller.signal)).rejects.toMatchObject({status:503});expect(fetch).not.toHaveBeenCalled();
  });
  it('rechecks desktop session currency after receiving bytes and before disclosure',async()=>{
    vi.stubGlobal('window',{location:{href:'app://cosmas/index.html'}});vi.stubEnv('VITE_API_BASE','app://cosmas/api');
    for(const key of ['VITE_WORKSPACE_DESKTOP_AUTH_ENABLED','VITE_DESKTOP_SYNTHETIC_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');
    let current=true;const signed={mode:'desktop_native' as const,revision:crypto.randomUUID(),isCurrent:()=>current};
    vi.mocked(fetch).mockImplementation(async()=>{current=false;return json(actual.catalog);});await expect(inboxApi.catalog(signed)).rejects.toMatchObject({status:503});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('denies disclosure if the desktop session changes while source and receipt hashes are verified',async()=>{
    vi.stubGlobal('window',{location:{href:'app://cosmas/index.html'}});vi.stubEnv('VITE_API_BASE','app://cosmas/api');
    for(const key of ['VITE_WORKSPACE_DESKTOP_AUTH_ENABLED','VITE_DESKTOP_SYNTHETIC_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');
    let current=true;const signed={mode:'desktop_native' as const,revision:crypto.randomUUID(),isCurrent:()=>current};
    vi.mocked(fetch).mockImplementation(async url=>json(String(url).endsWith('/history')?actual.history:actual.closed));
    vi.stubGlobal('crypto',{subtle:{digest:async(algorithm:AlgorithmIdentifier,data:BufferSource)=>{const hash=await webcrypto.subtle.digest(algorithm,data);current=false;return hash;}}});
    await expect(inboxApi.detail(signed,scope,itemId)).rejects.toMatchObject({status:503});expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('includes stalled exact operation hashing in the15s budget before obtaining credentials',async()=>{
    const op=await inboxFixtureOperation(),getToken=vi.fn(async()=> 'invented-token');vi.useFakeTimers();
    vi.stubGlobal('crypto',{subtle:{digest:()=>new Promise(()=>{})}});
    const result=expect(inboxApi.execute({mode:'clerk_jwt',getToken},op)).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(15001);await result;expect(getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
});
