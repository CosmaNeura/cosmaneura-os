import assert from 'node:assert/strict';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import test from 'node:test';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

// An explicit socket-port mapping keeps the already-running native trial service
// untouched. The product transport still supplies its fixed loopback host/8046.
test('connector main-process proxy and direct transport exchange real loopback bytes',async t=>{
  const id='00000000-0000-4000-8000-000000000001',base=`/workspaces/${id}`,pdfPath=base+`/vendor-artifacts/${id}/content`;
  const pdf=Buffer.from('%PDF-1.7\nInvented local document\n%%EOF');const seen=[];
  let mode='normal',entered;
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    seen.push({method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)});
    if(mode==='hold'){entered?.();return;}
    if(mode==='redirect'){res.writeHead(302,{Location:'https://outside.example.invalid'});res.end();return;}
    res.writeHead(200,{'Content-Type':req.method==='GET'&&req.url===pdfPath?'application/pdf':'application/json','Cache-Control':'no-store','Set-Cookie':'invented=never-forwarded'});
    res.end(req.method==='GET'&&req.url===pdfPath?pdf:'{"invented":true}');
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;
  const transport=(url,options)=>local(url,options,(address,callback)=>{assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);return httpRequest({...address,port},callback);});
  const ready={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
  function session(){let state=ready;const listeners=new Set();return {getState:async()=>state,snapshot:()=>state,getToken:async()=> 'invented.local.token',subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
  const make=(path,method='GET',body,extra={})=>new Request('app://cosmas/api'+path,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Vendor-Contract':'1',...extra},...(body===undefined?{}:{body})});
  try{
    await t.test('private PDF write/read preserves bytes and only the exact approved header surface',async()=>{
      const write=await proxy(make(pdfPath,'PUT',pdf,{'Content-Type':'application/pdf','X-Cosmas-Artifact-Write-Key':'invented-proof-key'}),session(),transport);
      assert.equal(write.status,200);assert.deepEqual(seen[0].body,pdf);assert.equal(seen[0].headers['x-cosmas-artifact-write-key'],'invented-proof-key');assert.equal(seen[0].headers['x-cosmas-vendor-contract'],'1');assert.equal(seen[0].headers.authorization,'Bearer invented.local.token');assert.equal(seen[0].headers['x-cosmas-desktop-session'],undefined);
      const read=await proxy(make(pdfPath),session(),transport);assert.equal(read.status,200);assert.equal(read.headers.get('set-cookie'),null);assert.deepEqual(Buffer.from(await read.arrayBuffer()),pdf);
    });
    await t.test('an encoded cursor reaches the fixed service while invalid query selectors never connect',async()=>{
      const path=base+'/vendor-work?cursor='+encodeURIComponent('invented:cursor/+==');
      assert.equal((await proxy(make(path),session(),transport)).status,200);assert.equal(seen.at(-1).path,path);
      const before=seen.length;assert.equal((await proxy(make(base+'/vendor-work?owner=outside'),session(),transport)).status,404);assert.equal(seen.length,before);
    });
    await t.test('redirects are rejected without a second destination request',async()=>{
      mode='redirect';const before=seen.length;assert.equal((await proxy(make(base+'/vendor-work/options'),session(),transport)).status,503);assert.equal(seen.length,before+1);
    });
    await t.test('sign-out cancels a pending socket response before private bytes are released',async()=>{
      mode='hold';const admitted=new Promise(resolve=>{entered=resolve;}),auth=session();const pending=proxy(make(pdfPath),auth,transport);
      await admitted;auth.revoke();assert.equal((await pending).status,401);
    });
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
