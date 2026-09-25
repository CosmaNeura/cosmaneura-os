import assert from 'node:assert/strict';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

// The socket factory remaps only the port to an ephemeral listener. No test
// binds or connects to the W35 service at the product's fixed port 8046.
test('finance settings traverse the actual native proxy and direct loopback HTTP transport',async t=>{
  const fixture=JSON.parse(await readFile(new URL('../../web/src/__fixtures__/finance-setup/actual-finance-setup-fixtures.json',import.meta.url),'utf8'));
  const id='00000000-0000-4000-8000-000000000001',setup=fixture.details[0].summary.setup_id,header='X-Cosmas-Finance-Setup-Contract';
  const seen=[];let mode='normal',entered;
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);seen.push({method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)});
    if(mode==='hold'){entered?.();return;}
    if(mode==='redirect'){res.writeHead(302,{Location:'https://outside.example.invalid/never-requested'});res.end();return;}
    res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'invented=never-forwarded'});
    if(mode==='oversize'){res.write('"'+'x'.repeat(65536));res.end('x'.repeat(65536)+'"');return;}
    if(req.method==='GET')res.end(JSON.stringify(req.url==='/finance-setup'?fixture.active_catalog:req.url.endsWith('/history')?fixture.history:fixture.details[0]));
    else{const body=JSON.parse(seen.at(-1).body.toString('utf8'));const index=fixture.commands.findIndex(c=>c.kind===req.url.split('/').at(-1)&&c.request.idempotency_key===body.idempotency_key);res.end(JSON.stringify(index<0?{transport_only:true}:fixture.receipts[index]));}
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;assert.notEqual(port,8046);
  let socketCalls=0;
  const transport=(url,options)=>local(url,options,(address,callback)=>{socketCalls++;assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);assert.equal(address.agent,false);return httpRequest({...address,port},callback);});
  function auth(){let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};const listeners=new Set();return {getState:async()=>state,snapshot:()=>state,getToken:async()=> 'invented.local.token',subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
  const request=(path,method='GET',body,extra={})=>new Request('app://cosmas/api'+path,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1',...extra},...(body===undefined?{}:{body})});
  try{
    await t.test('reads actual fixture catalogs, detail and history through the fixed-origin socket seam',async()=>{
      for(const [path,expected] of [['/finance-setup',fixture.active_catalog],[`/finance-setup/${setup}`,fixture.details[0]],[`/finance-setup/${setup}/history`,fixture.history]]){const response=await proxy(request(path),auth(),transport);assert.equal(response.status,200);assert.deepEqual(await response.json(),expected);assert.equal(seen.at(-1).path,path);assert.equal(seen.at(-1).method,'GET');assert.equal(seen.at(-1).headers[header.toLowerCase()],'1');assert.equal(seen.at(-1).headers.authorization,'Bearer invented.local.token');assert.equal(seen.at(-1).headers['x-cosmas-desktop-session'],undefined);assert.equal(response.headers.get('set-cookie'),null);}
    });
    await t.test('preserves all four actual setup command and receipt fixture bytes without any processor endpoint',async()=>{
      for(const [index,command] of fixture.commands.entries()){const body=JSON.stringify(command.request);const response=await proxy(request('/finance-setup/'+command.kind,'POST',body),auth(),transport);assert.equal(response.status,200);assert.deepEqual(seen.at(-1).body,Buffer.from(body));assert.equal(seen.at(-1).method,'POST');assert.deepEqual(await response.json(),fixture.receipts[index]);}
      const bound=fixture.commands[1].request,base={setup_id:bound.setup_id,expected_version:bound.expected_version,revision_id:bound.revision_id,review_sha256:bound.review_sha256,idempotency_key:'invented-transport-only'};
      for(const [kind,body] of [['disable',{...base,confirm_disable:true}],['revoke',{...base,confirm_revoke:true}],['resolve',{command_kind:'propose_account',idempotency_key:fixture.commands[0].request.idempotency_key,request_sha256:fixture.receipts[0].request_sha256}]]){const raw=JSON.stringify(body);assert.equal((await proxy(request('/finance-setup/'+kind,'POST',raw),auth(),transport)).status,200);assert.deepEqual(seen.at(-1).body,Buffer.from(raw));}
    });
    await t.test('invalid query/header/credential and oversized command paths never open a socket',async()=>{
      const before=socketCalls;
      assert.equal((await proxy(request('/finance-setup?cursor=outside'),auth(),transport)).status,404);
      assert.equal((await proxy(request('/finance-setup','GET',undefined,{'X-Cosmas-Finance-Contract':'1'}),auth(),transport)).status,426);
      assert.equal((await proxy(request('/finance-setup','GET',undefined,{Authorization:'Bearer renderer-secret'}),auth(),transport)).status,401);
      assert.equal((await proxy(request('/finance-setup/activate','POST','"'+'x'.repeat(8191)+'"'),auth(),transport)).status,503);
      assert.equal(socketCalls,before);
    });
    await t.test('rejects a chunked oversized private catalog with one request and no partial disclosure',async()=>{
      mode='oversize';const before=socketCalls;const response=await proxy(request('/finance-setup'),auth(),transport);assert.equal(response.status,503);assert.equal(socketCalls,before+1);assert.ok((await response.text()).length<256);
    });
    await t.test('refuses redirects without a second socket or alternate destination',async()=>{
      mode='redirect';const before=socketCalls;assert.equal((await proxy(request('/finance-setup'),auth(),transport)).status,503);assert.equal(socketCalls,before+1);
    });
    await t.test('revocation cancels a pending socket response before private settings are returned',async()=>{
      mode='hold';const accepted=new Promise(resolve=>{entered=resolve;}),session=auth();const pending=proxy(request(`/finance-setup/${setup}`),session,transport);await accepted;session.revoke();assert.equal((await pending).status,401);
    });
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
