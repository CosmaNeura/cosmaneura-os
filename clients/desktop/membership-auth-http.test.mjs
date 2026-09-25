import assert from 'node:assert/strict';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

// Only the injected socket port changes: the product still admits the exact
// 8046 target, and this test never binds or contacts an existing native service.
test('membership review traverses the native proxy and actual direct HTTP socket',async t=>{
  const load=async name=>JSON.parse(await readFile(new URL('../../web/src/__fixtures__/membership/'+name,import.meta.url),'utf8'));
  const fixture=await load('actual-membership-process.json'),http=await load('actual-membership-http.json'),manual=await load('actual-membership-manual-evidence.json');
  const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Membership-Contract';
  const root=f=>`/workspaces/${f.detail.scope.workspace_id}/membership-work`,base=root(fixture),ticket=base+'/'+fixture.detail.summary.ticket_id;
  const reads=new Map([[root(http)+'/options',http.options],[ticket,fixture.detail],[ticket+'/history',fixture.history],
    [root(manual)+'/'+manual.detail.summary.ticket_id,manual.detail],[root(manual)+'/'+manual.detail.summary.ticket_id+'/history',manual.history]]);
  const seen=[];let mode='normal',entered;
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);seen.push({method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)});
    if(mode==='hold'){entered?.();return;}
    if(mode==='redirect'){res.writeHead(302,{Location:'https://outside.example.invalid/never-requested'});res.end();return;}
    res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'invented=never-forwarded'});
    if(mode==='oversize'){res.write('"'+'x'.repeat(524288));res.end('x'.repeat(524288)+'"');return;}
    if(req.method==='GET'){res.end(JSON.stringify(reads.get(req.url)));return;}
    const body=JSON.parse(seen.at(-1).body.toString('utf8'));
    const kind=req.url===base?'propose':req.url.endsWith('/resolve')?body.command_kind:req.url.split('/').at(-1);
    const item=fixture.history.items.find(i=>i.receipt.command_kind===kind&&i.request.idempotency_key===body.idempotency_key);
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
    await t.test('preserves actual options and both local/manual evidence detail/history bytes',async()=>{
      await Promise.all([...reads].map(async([path,expected])=>{
        const response=await proxy(request(path),auth(),transport);assert.equal(response.status,200);assert.deepEqual(await response.json(),expected);
        assert.equal(response.headers.get('set-cookie'),null);assert.equal(response.headers.get('cache-control'),'no-store');
        if(expected.summary){assert.equal(expected.summary.external_service_verified,false);assert.equal(expected.summary.membership_authority,'not_established');}
      }));
      for(const row of seen){assert.equal(row.method,'GET');assert.ok(reads.has(row.path));assert.equal(row.headers[header.toLowerCase()],'1');assert.equal(row.headers.authorization,'Bearer invented.local.token');assert.equal(row.headers['x-cosmas-desktop-session'],undefined);}
    });
    await t.test('preserves signed-process proposal, decision, result and verification request/receipt fixtures',async()=>{
      for(const item of fixture.history.items){
        const kind=item.receipt.command_kind,path=kind==='propose'?base:ticket+'/'+kind,body=JSON.stringify(item.request);
        const response=await proxy(request(path,'POST',body),auth(),transport);assert.equal(response.status,200);
        assert.deepEqual(seen.at(-1).body,Buffer.from(body));assert.equal(seen.at(-1).path,path);assert.equal(seen.at(-1).method,'POST');assert.deepEqual(await response.json(),item.receipt);
      }
    });
    await t.test('exact resolver requests return existing fixture receipts without resending their command',async()=>{
      for(const item of fixture.history.items){
        const {command_kind,idempotency_key,request_sha256}=item.receipt,body=JSON.stringify({command_kind,idempotency_key,request_sha256});
        const before=socketCalls,response=await proxy(request(base+'/resolve','POST',body),auth(),transport);
        assert.equal(response.status,200);assert.equal(socketCalls,before+1);assert.equal(seen.at(-1).path,base+'/resolve');assert.deepEqual(seen.at(-1).body,Buffer.from(body));assert.deepEqual(await response.json(),item.receipt);
      }
      // Withdrawal has transport coverage only here; no invented semantic receipt.
      const raw='{"idempotency_key":"invented-withdraw-transport-only"}';
      assert.equal((await proxy(request(ticket+'/withdraw','POST',raw),auth(),transport)).status,200);assert.deepEqual(seen.at(-1).body,Buffer.from(raw));
    });
    await t.test('unknown methods/routes, queries, headers, credentials and oversize input open no socket',async()=>{
      const before=socketCalls;
      for(const path of [base+'?cursor=outside',ticket+'/submit',ticket+'/charge',ticket+'/observations'])assert.equal((await proxy(request(path),auth(),transport)).status,404);
      assert.equal((await proxy(request(base,'PUT','{}'),auth(),transport)).status,404);
      assert.equal((await proxy(request(base,'GET',undefined,{'X-Cosmas-Finance-Contract':'1'}),auth(),transport)).status,426);
      assert.equal((await proxy(request(base,'GET',undefined,{Authorization:'Bearer renderer-secret'}),auth(),transport)).status,401);
      assert.equal((await proxy(request(base,'POST','"'+'x'.repeat(8191)+'"'),auth(),transport)).status,503);
      assert.equal(socketCalls,before);
    });
    await t.test('rejects chunked history over 1MiB with one request and no partial disclosure',async()=>{
      mode='oversize';const before=socketCalls,response=await proxy(request(ticket+'/history'),auth(),transport);
      assert.equal(response.status,503);assert.equal(socketCalls,before+1);assert.ok((await response.text()).length<256);
    });
    await t.test('rejects redirect without a second socket or alternate destination',async()=>{
      mode='redirect';const before=socketCalls;assert.equal((await proxy(request(ticket),auth(),transport)).status,503);assert.equal(socketCalls,before+1);
    });
    await t.test('caller cancellation preserves its original boundary and does not retry',async()=>{
      mode='hold';const controller=new AbortController(),accepted=new Promise(resolve=>{entered=resolve;});
      const before=socketCalls,pending=proxy(request(ticket,'GET',undefined,{},controller.signal),auth(),transport);
      await accepted;controller.abort();assert.equal((await pending).status,503);assert.equal(socketCalls,before+1);
    });
    await t.test('session revocation prevents a pending private history response from being disclosed',async()=>{
      mode='hold';const accepted=new Promise(resolve=>{entered=resolve;}),session=auth();
      const pending=proxy(request(ticket+'/history'),session,transport);await accepted;session.revoke();assert.equal((await pending).status,401);
    });
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
