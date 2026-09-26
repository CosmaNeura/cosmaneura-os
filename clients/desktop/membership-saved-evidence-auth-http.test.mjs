import assert from 'node:assert/strict';
import test from 'node:test';
import net from 'node:net';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

// The guard is in this test file as well as the full runner; standalone runs
// may use only their own process's new ephemeral loopback listener.
function guardNetwork(){
  const listen=net.Server.prototype.listen,connect=net.Socket.prototype.connect,ports=new Set();
  const options=args=>{const a=Array.isArray(args[0])?args[0]:args;return typeof a[0]==='object'&&a[0]!==null?a[0]:{port:a[0],host:typeof a[1]==='string'?a[1]:'localhost'};};
  net.Server.prototype.listen=function(...args){
    const value=options(args);assert.equal(value.port,0,'Only ephemeral listeners');assert.equal(value.host,'127.0.0.1','Only loopback listeners');
    this.once('listening',()=>{const port=this.address().port;ports.add(port);this.once('close',()=>ports.delete(port));});
    return Reflect.apply(listen,this,args);
  };
  net.Socket.prototype.connect=function(...args){
    const value=options(args);
    if((value.host??value.hostname)!=='127.0.0.1'||!ports.has(Number(value.port)))throw Error('Unowned test socket denied');
    return Reflect.apply(connect,this,args);
  };
  return()=>{net.Server.prototype.listen=listen;net.Socket.prototype.connect=connect;};
}

test('saved evidence transports exact real backend JSON only through an owned ephemeral socket',async t=>{
 const restore=guardNetwork();let server;
 try{
  for(const port of [8046,8047,8197,8246,8247,8248,8256])assert.throws(()=>httpRequest({host:'127.0.0.1',port,path:'/never'}),/Unowned test socket denied/);
  const fixture=JSON.parse(await readFile(new URL('../../web/src/__fixtures__/membership/actual-membership-cross-device-evidence.json',import.meta.url),'utf8'));
  const expected=Buffer.from(JSON.stringify(fixture.response)),scope=fixture.response.scope,binding=fixture.response.membership;
  assert.ok(expected.length<=65536);assert.equal(binding.result_receipt_id,fixture.membership_detail.latest_result.receipt_id);
  const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Membership-Contract',path=`/workspaces/${scope.workspace_id}/membership-work/${binding.ticket_id}/results/${binding.result_receipt_id}/finance-evidence`;
  let mode='normal',entered,sockets=0;const seen=[];
  server=createServer(async(req,res)=>{
   const chunks=[];for await(const part of req)chunks.push(part);const row={method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)};seen.push(row);assert.equal(row.method,'GET');assert.equal(row.path,path);assert.equal(row.body.length,0);
   if(mode==='hold'){entered?.();return;}if(mode==='lost'){res.destroy();return;}if(mode==='redirect'){res.writeHead(302,{Location:'https://outside.invalid/never'});res.end();return;}
   res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'invented=withheld'});
   if(mode==='oversize'){res.write('"'+'x'.repeat(32768));res.end('x'.repeat(32767)+'"');return;}
   res.write(expected.subarray(0,100));res.end(expected.subarray(100));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;
  const transport=(url,options)=>local(url,options,(address,callback)=>{sockets++;assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);assert.equal(address.agent,false);return httpRequest({...address,port},callback);});
  function auth(){let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};const listeners=new Set();return {getState:async()=>state,snapshot:()=>state,getToken:async()=>'invented.local.token',subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
  const request=(target=path,extra={},signal,method='GET')=>new Request('app://cosmas/api'+target,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1',...extra},signal});
  await t.test('preserves actual original request, immutable receipt and current detail bytes without cookies or renderer identity',async()=>{
   const response=await proxy(request(),auth(),transport);assert.equal(response.status,200);assert.deepEqual(Buffer.from(await response.arrayBuffer()),expected);assert.equal(response.headers.get('set-cookie'),null);assert.equal(sockets,1);assert.equal(seen[0].headers.authorization,'Bearer invented.local.token');assert.equal(seen[0].headers[header.toLowerCase()],'1');assert.equal(seen[0].headers['x-cosmas-desktop-session'],undefined);
  });
  await t.test('invalid method, path, header and renderer authority open no socket',async()=>{
   const before=sockets;
   for(const target of [path+'?finance_ticket=other',path+'/extra',path.replace('/results/','/result/')])assert.equal((await proxy(request(target),auth(),transport)).status,404);
   assert.equal((await proxy(request(path,{},undefined,'POST'),auth(),transport)).status,404);
   assert.equal((await proxy(request(path,{'X-Cosmas-Finance-Contract':'1'}),auth(),transport)).status,426);assert.equal((await proxy(request(path,{Authorization:'Bearer renderer-invented'}),auth(),transport)).status,401);assert.equal(sockets,before);
  });
  await t.test('lost read response has no automatic resend; a new explicit read can inspect the same evidence',async()=>{
   mode='lost';const before=sockets;assert.equal((await proxy(request(),auth(),transport)).status,503);assert.equal(sockets,before+1);mode='normal';const response=await proxy(request(),auth(),transport);assert.equal(response.status,200);assert.deepEqual(Buffer.from(await response.arrayBuffer()),expected);assert.equal(sockets,before+2);
  });
  await t.test('chunked response above 64 KiB and redirect are withheld with exactly one local request each',async()=>{
   for(const value of ['oversize','redirect']){mode=value;const before=sockets,response=await proxy(request(),auth(),transport);assert.equal(response.status,503);assert.equal(sockets,before+1);assert.ok((await response.text()).length<256);}
  });
  await t.test('abort and native sign-out discard held responses without replay or partial evidence',async()=>{
   mode='hold';const before=sockets;let accepted=new Promise(resolve=>{entered=resolve;});const abort=new AbortController();let pending=proxy(request(path,{},abort.signal),auth(),transport);await accepted;abort.abort();assert.equal((await pending).status,503);assert.equal(sockets,before+1);
   accepted=new Promise(resolve=>{entered=resolve;});const session=auth();pending=proxy(request(),session,transport);await accepted;session.revoke();assert.equal((await pending).status,401);assert.equal(sockets,before+2);
  });
 }finally{if(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}restore();}
});
