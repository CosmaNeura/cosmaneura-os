import assert from 'node:assert/strict';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

// The product still admits only its fixed 8046 target. This socket seam maps
// that target to a fresh ephemeral test port; it never contacts a running app.
// The HTTP/process exports are recorded synthetic backend facts, replayed here
// to qualify transport bytes, not to claim another live backend/service trial.
test('vendor settings traverse the native proxy and actual direct HTTP socket',async t=>{
  const load=async name=>JSON.parse(await readFile(new URL('../../web/src/__fixtures__/vendor-setup/'+name,import.meta.url),'utf8'));
  const fixture=await load('actual-vendor-settings-process.json'),http=await load('actual-vendor-settings-http-r2.json');
  const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Vendor-Setup-Contract',base='/vendor-settings';
  const detail=base+'/'+fixture.recipient_detail.summary.setup_id;
  const reads=new Map([[base,http.catalog],[base+'/'+http.detail.summary.setup_id,http.detail],
    [base+'/'+http.detail.summary.setup_id+'/history',http.history],
    [base+'/'+fixture.account_detail.summary.setup_id,fixture.account_detail],
    [detail,fixture.recipient_detail],[detail+'/history',fixture.history]]);
  const commands=[
    {kind:'propose_account',request:http.account_request,receipt:http.account_receipt},
    {kind:'propose_account',request:fixture.account_request,receipt:fixture.proposal_receipt},
    {kind:'activate',request:fixture.activation_request,receipt:fixture.activation_receipt},
    {kind:'propose_recipient',request:fixture.recipient_request,receipt:fixture.recipient_proposal_receipt},
    {kind:'activate',request:fixture.recipient_activation_request,receipt:fixture.recipient_activation_receipt},
  ];
  const seen=[];let mode='normal',entered;
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    const row={method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)};seen.push(row);
    if(mode==='hold'){entered?.();return;}
    if(mode==='lostreply'){res.destroy();return;}
    if(mode==='redirect'){res.writeHead(302,{Location:'https://outside.example.invalid/never-requested'});res.end();return;}
    res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'invented=never-forwarded'});
    if(mode==='oversize'){res.write('"'+'x'.repeat(524288));res.end('x'.repeat(524288)+'"');return;}
    if(req.method==='GET'){assert.ok(reads.has(req.url));res.end(JSON.stringify(reads.get(req.url)));return;}
    const body=JSON.parse(row.body.toString('utf8'));
    const resolve=req.url===base+'/resolve',kind=resolve?body.command_kind:req.url.split('/').at(-1);
    const item=commands.find(c=>c.kind===kind&&c.request.idempotency_key===body.idempotency_key);
    if(item){
      assert.deepEqual(body,resolve?{command_kind:item.kind,idempotency_key:item.receipt.idempotency_key,request_sha256:item.receipt.request_sha256}:item.request);
    }
    res.end(JSON.stringify(item?item.receipt:{transport_only:true}));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;assert.notEqual(port,8046);
  let socketCalls=0;
  const transport=(url,options)=>local(url,options,(address,callback)=>{
    socketCalls++;assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);assert.equal(address.agent,false);
    return httpRequest({...address,port},callback);
  });
  function auth(){let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};const listeners=new Set();return {getState:async()=>state,snapshot:()=>state,getToken:async()=>'invented.local.token',subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
  const request=(path,method='GET',body,extra={},signal)=>new Request('app://cosmas/api'+path,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1',...extra},...(body===undefined?{}:{body}),signal});
  try{
    await t.test('preserves frozen catalog, account/recipient details and histories across concurrent signed reads',async()=>{
      await Promise.all([...reads].map(async([path,expected])=>{
        const response=await proxy(request(path),auth(),transport);assert.equal(response.status,200);assert.deepEqual(await response.json(),expected);
        assert.equal(response.headers.get('set-cookie'),null);assert.equal(response.headers.get('cache-control'),'no-store');
      }));
      for(const row of seen){assert.equal(row.method,'GET');assert.ok(reads.has(row.path));assert.equal(row.headers[header.toLowerCase()],'1');assert.equal(row.headers.authorization,'Bearer invented.local.token');assert.equal(row.headers['x-cosmas-desktop-session'],undefined);assert.equal(row.headers['x-cosmas-vendor-contract'],undefined);}
    });
    await t.test('preserves exact account/recipient proposals and separately reviewed activation request/receipt bytes',async()=>{
      for(const item of commands){
        const path=base+'/'+item.kind,body=JSON.stringify(item.request),response=await proxy(request(path,'POST',body),auth(),transport);
        assert.equal(response.status,200);assert.deepEqual(seen.at(-1).body,Buffer.from(body));assert.equal(seen.at(-1).path,path);assert.equal(seen.at(-1).method,'POST');assert.deepEqual(await response.json(),item.receipt);
      }
      // These two commands have route/byte coverage, not fabricated state receipts.
      for(const kind of ['disable','revoke']){
        const r=fixture.recipient_activation_request,body=JSON.stringify({setup_id:r.setup_id,expected_version:r.expected_version,revision_id:r.revision_id,review_sha256:r.review_sha256,idempotency_key:'invented-transport-only-'+kind,['confirm_'+kind]:true});
        const response=await proxy(request(base+'/'+kind,'POST',body),auth(),transport);assert.equal(response.status,200);assert.deepEqual(seen.at(-1).body,Buffer.from(body));assert.deepEqual(await response.json(),{transport_only:true});
      }
    });
    await t.test('exact resolver requests return retained receipts without repeating their original command',async()=>{
      for(const item of commands){
        const {command_kind,idempotency_key,request_sha256}=item.receipt,body=JSON.stringify({command_kind,idempotency_key,request_sha256});
        const before=socketCalls,response=await proxy(request(base+'/resolve','POST',body),auth(),transport);
        assert.equal(response.status,200);assert.equal(socketCalls,before+1);assert.equal(seen.at(-1).path,base+'/resolve');assert.deepEqual(seen.at(-1).body,Buffer.from(body));assert.deepEqual(await response.json(),item.receipt);
      }
    });
    await t.test('a lost reply opens one socket; explicit resolve retrieves the retained receipt without an automatic resend',async()=>{
      mode='lostreply';const item=commands[2],before=socketCalls,seenBefore=seen.length;
      const response=await proxy(request(base+'/'+item.kind,'POST',JSON.stringify(item.request)),auth(),transport);
      assert.equal(response.status,503);assert.equal(socketCalls,before+1);assert.equal(seen.length,seenBefore+1);assert.equal(seen.at(-1).path,base+'/'+item.kind);
      mode='normal';const {command_kind,idempotency_key,request_sha256}=item.receipt;
      const recovered=await proxy(request(base+'/resolve','POST',JSON.stringify({command_kind,idempotency_key,request_sha256})),auth(),transport);
      assert.equal(recovered.status,200);assert.deepEqual(await recovered.json(),item.receipt);assert.equal(socketCalls,before+2);assert.deepEqual(seen.slice(seenBefore).map(r=>r.path),[base+'/'+item.kind,base+'/resolve']);
    });
    await t.test('unknown methods/routes, queries, headers, renderer credentials and oversize input open no socket',async()=>{
      const before=socketCalls;
      for(const path of [base+'?cursor=outside',base+'/submit',base+'/credentials',detail+'/activate',detail+'/observations'])assert.equal((await proxy(request(path),auth(),transport)).status,404);
      assert.equal((await proxy(request(base,'PUT','{}'),auth(),transport)).status,404);
      assert.equal((await proxy(request(base,'GET',undefined,{'X-Cosmas-Vendor-Contract':'1'}),auth(),transport)).status,426);
      assert.equal((await proxy(request(base,'GET',undefined,{Authorization:'Bearer renderer-secret'}),auth(),transport)).status,401);
      assert.equal((await proxy(request(base+'/activate','POST','"'+'x'.repeat(8191)+'"'),auth(),transport)).status,503);
      assert.equal(socketCalls,before);
    });
    await t.test('rejects chunked history over 1MiB with one request and no partial disclosure',async()=>{
      mode='oversize';const before=socketCalls,response=await proxy(request(detail+'/history'),auth(),transport);
      assert.equal(response.status,503);assert.equal(socketCalls,before+1);assert.ok((await response.text()).length<256);
    });
    await t.test('rejects redirect without a second socket or alternate destination',async()=>{
      mode='redirect';const before=socketCalls;assert.equal((await proxy(request(detail),auth(),transport)).status,503);assert.equal(socketCalls,before+1);
    });
    await t.test('caller cancellation stops a held response and does not retry',async()=>{
      mode='hold';const controller=new AbortController(),accepted=new Promise(resolve=>{entered=resolve;});
      const before=socketCalls,pending=proxy(request(detail,'GET',undefined,{},controller.signal),auth(),transport);
      await accepted;controller.abort();assert.equal((await pending).status,503);assert.equal(socketCalls,before+1);
    });
    await t.test('session revocation prevents a pending private history response from being disclosed',async()=>{
      mode='hold';const accepted=new Promise(resolve=>{entered=resolve;}),session=auth();
      const pending=proxy(request(detail+'/history'),session,transport);await accepted;session.revoke();assert.equal((await pending).status,401);
    });
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
