import {afterEach,expect,it,vi} from 'vitest';
import {faxCommitment,faxInboundRequest,validateFaxPending,validFaxScope,validateFaxMetadata,faxInboundApi} from './fax-inbound-api';
import {WorkspaceApiError} from './workspace-api';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');});
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`;
afterEach(()=>vi.unstubAllGlobals());
it('binds the retained Python commitment for unicode account labels',async()=>{
 vi.stubGlobal('crypto',webcrypto);
 expect(await faxCommitment({label:'Café 🩺',scope:{box_id:id(1),owner_id:id(2)}})).toBe('0e5b8eb9e3983d87d5aef42ce107d53dace519ab638fd0682b91d827cd905ada');
});
it('rejects authority and provider locations outside the public command contract',()=>{
 expect(validFaxScope({box_id:id(1),owner_id:id(2)})).toBe(true);
 expect(validFaxScope({box_id:id(1),owner_id:id(2),vendor_url:'https://example.invalid'})).toBe(false);
 const request={idempotency_key:id(3),connection_id:id(4),reviewed_account:true as const,image_enabled:false,expires_at:'2026-10-03T20:00:00Z'};
 expect(validateFaxPending({kind:'grant',request}).request).toEqual(request);
 for(const addition of [{provider_url:'https://example.invalid'},{secret:'invented-secret'},{reviewed_account:false}])expect(()=>validateFaxPending({kind:'grant',request:{...request,...addition}})).toThrow(WorkspaceApiError);
});
it('bounds observations to one seven-day page and exact approval commands',()=>{
 const request={idempotency_key:id(3),grant_id:id(4),starts_at:'2026-09-26T12:00:00Z',ends_at:'2026-10-03T12:00:00Z',limit:25};
 expect(validateFaxPending({kind:'observe',request}).request).toEqual(request);
 for(const patch of [{limit:26},{limit:true},{starts_at:'2026-09-25T12:00:00Z'},{ends_at:request.starts_at}])expect(()=>validateFaxPending({kind:'observe',request:{...request,...patch}})).toThrow(WorkspaceApiError);
 const decision={idempotency_key:id(3),ticket_id:id(4),revision_id:id(5),expected_version:1,choice:'approve',reviewed_exact_fax:true};
 expect(validateFaxPending({kind:'decide',request:decision}).request).toEqual(decision);
 expect(()=>validateFaxPending({kind:'decide',request:{...decision,reviewed_exact_fax:false}})).toThrow(WorkspaceApiError);
 expect(()=>validateFaxPending({kind:'acquire',request:{idempotency_key:id(3),ticket_id:id(4),revision_id:id(5),expected_version:1,approval_sha256:'a'.repeat(63)}})).toThrow(WorkspaceApiError);
});

it('uses the signed product endpoint once and refuses malformed provider responses',async()=>{
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({error:'fax_inbound_not_configured'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
 const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
 await expect(faxInboundRequest(identity,'/fax-inbound',undefined)).rejects.toMatchObject({status:409,code:'fax_inbound_not_configured'});
 expect(fetcher).toHaveBeenCalledOnce();const [url,init]=fetcher.mock.calls[0] as unknown as [string,RequestInit];
 expect(url).toBe('http://127.0.0.1:8000/fax-inbound');expect(init).toMatchObject({method:'GET',cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'});
 expect(new Headers(init.headers).get('Authorization')).toBe('Bearer invented-token');expect(new Headers(init.headers).get('X-Cosmas-Fax-Inbound')).toBe('1');
 await expect(faxInboundRequest(identity,'https://example.invalid/fax-inbound',undefined)).rejects.toMatchObject({status:422});expect(fetcher).toHaveBeenCalledOnce();
});
it('bounds decoded response bytes and leaves interrupted requests unretried',async()=>{
 const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
 const oversize=vi.fn(async()=>new Response(' '.repeat(131073),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',oversize);
 await expect(faxInboundRequest(identity,'/fax-inbound',undefined)).rejects.toMatchObject({status:502});expect(oversize).toHaveBeenCalledOnce();
 const c=new AbortController();c.abort();const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
 await expect(faxInboundRequest(identity,'/fax-inbound',undefined,c.signal)).rejects.toMatchObject({status:503,code:'fax_inbound_unconfirmed'});expect(fetcher).not.toHaveBeenCalled();
});

it('accepts nullable provider viewed status and validates all sender provenance',()=>{
 const metadata={ordinal:1,source_sha256:'a'.repeat(64),sender_label:'Café 🩺',sender_number:null,sender_identity:'provider_reported_unverified',received_at:'2026-10-05T18:00:00Z',pages:1,viewed:null,image_available:true,image_block_reason:null};
 expect(validateFaxMetadata(metadata)).toEqual(metadata);
 for(const change of [{sender_identity:'verified_patient'},{sender_number:5},{sender_number:'\nPRIVATE'},{sender_label:'   '},{viewed:'false'},{unexpected:'private'}])expect(()=>validateFaxMetadata({...metadata,...change})).toThrow();
});
it('calls only the singular signed proposal route',async()=>{
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({error:'fax_inbound_not_configured'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
 await expect(faxInboundApi.proposal({mode:'clerk_jwt',getToken:async()=> 'invented-token'},{box_id:id(1),owner_id:id(2)},id(3),id(4))).rejects.toMatchObject({status:409});
 expect((fetcher.mock.calls[0] as unknown as [string])[0]).toBe('http://127.0.0.1:8000/fax-inbound/proposal/'+id(3)+'/'+id(4));
});

it('rejects redirected or cacheable received-fax responses without retrying or reading their bodies',async()=>{
 const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
 for(const redirected of [true,false]){
  const response=new Response(JSON.stringify({contract_version:1,installations:[],grants:[]}),{headers:{'Content-Type':'application/json',...(redirected?{'Cache-Control':'no-store'}:{'Cache-Control':'private, max-age=60'})}});
  if(redirected)Object.defineProperty(response,'redirected',{value:true});const read=vi.spyOn(response.body!,'getReader'),fetcher=vi.fn(async()=>response);vi.stubGlobal('fetch',fetcher);
  await expect(faxInboundRequest(identity,'/fax-inbound',undefined)).rejects.toMatchObject({status:502,code:'fax_inbound_response_invalid'});
  expect(fetcher).toHaveBeenCalledOnce();expect(read).not.toHaveBeenCalled();
 }
});
