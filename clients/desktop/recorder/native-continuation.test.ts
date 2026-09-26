import {EventEmitter} from 'node:events';
import {PassThrough,Writable} from 'node:stream';
import {spawn} from 'node:child_process';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {realpathSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {afterEach,expect,it,vi} from 'vitest';
import {NativeProcessPCMDriver} from './native-process-driver';
import {nativeCommand} from './native-process-wire';
import type {CaptureSourceExtension} from '../../capture/src/configured/capture';

// Only in-memory inherited pipes. No child, microphone, permissions or key store.
vi.mock('node:child_process',()=>({spawn:vi.fn()}));
const cleanup:(()=>Promise<void>)[]=[];
afterEach(async()=>{for(const close of cleanup.splice(0).reverse())await close();vi.clearAllMocks();});
function gate(){let release!:()=>void;return {promise:new Promise<void>(r=>{release=r;}),release:()=>release()};}
async function fixture(){
  const directory=await mkdtemp(join(realpathSync(tmpdir()),'cosmas-private-pipe-'));
  cleanup.push(()=>rm(directory,{recursive:true,force:true}));
  const helperPath=join(directory,'controlled-input'),bytes=Buffer.from('invented never-executed helper');
  await writeFile(helperPath,bytes,{mode:0o755});
  const deadline=Date.now()+900_000,owner={runId:crypto.randomUUID(),generation:1,hardMaximumChunks:360};
  const request:CaptureSourceExtension={leaseReceiptId:crypto.randomUUID(),leaseGeneration:2,
    captureAuthorizedUntil:new Date(deadline+840_000).toISOString(),reservationBatchId:crypto.randomUUID(),
    firstSequenceNumber:84,reservationCount:90,maximumChunks:174};
  const permit={runId:owner.runId,generation:2,expiresAt:Date.now()+15_000,
    previousCaptureAuthorizedUntil:deadline,captureAuthorizedUntil:deadline+840_000,maximumChunks:174};
  const authorize=vi.fn(async()=>permit),commands:Record<string,unknown>[]=[];
  const child=new EventEmitter() as EventEmitter & {stdin:Writable;stdout:PassThrough};
  child.stdout=new PassThrough();
  const reply=(value:Record<string,unknown>)=>child.stdout.write(nativeCommand(value));
  let answerExtension=true;
  child.stdin=new Writable({write(frame:Buffer,_encoding,done){
    const command=JSON.parse(frame.subarray(5).toString()) as Record<string,unknown>;commands.push(command);
    queueMicrotask(()=>{
      if(command.type==='start')reply({type:'ready',start:{hostTimeNanoseconds:'1000000000',microphonePrerollNanoseconds:'0',systemPrerollNanoseconds:'0'}});
      if(command.type==='extend'&&answerExtension)reply({type:'extended',request:command.request,permit:command.permit});
      if(command.type==='stop')reply({type:'stopped',request:command.request,completion:null});
    });done();
  },final(done){done();queueMicrotask(()=>child.emit('close',0));}});
  vi.mocked(spawn).mockReturnValue(child as unknown as ReturnType<typeof spawn>);
  const driver=new NativeProcessPCMDriver({enabled:true,helperPath,helperSha256:createHash('sha256').update(bytes).digest('hex'),
    isSessionActive:()=>true,authorizeSelectedWindow:async()=>({application:'com.google.Chrome',processID:1,windowID:1,captureAuthorizedUntil:deadline}),
    getProcessFence:()=>({epoch:crypto.randomUUID(),coordinatorDevice:'1',coordinatorInode:'1',captureDevice:'1',captureInode:'2'}),
    continuation:{getOwner:()=>owner,authorize}});
  const session=driver.start({sampleRateHz:16000,maximumOutputFrames:89*160000,targetFramesPerChunk:160000},
    {onPcmPacket:async()=>{},onFailure:()=>{}});
  cleanup.push(async()=>{await session.stop({mode:'discard'});});
  await session.ready;session.activate();
  return {session,request,permit,authorize,commands,reply,delayReply:()=>{answerExtension=false;}};
}

it('uses one process and forwards only the exact native permit after authorization',async()=>{
  const f=await fixture();await f.session.extend!(f.request);
  expect(spawn).toHaveBeenCalledOnce();expect(f.authorize).toHaveBeenCalledWith(f.request);
  expect(f.commands.find(c=>c.type==='extend')?.permit).toEqual(f.permit);
  expect(f.commands.filter(c=>c.type==='start')).toHaveLength(1);
  await f.session.stop({mode:'discard'});
  await expect(f.session.extend!(f.request)).rejects.toThrow();expect(f.authorize).toHaveBeenCalledOnce();
});

it('does not forward an authorized extension after Stop races the auth reply',async()=>{
  const f=await fixture(),pending=gate();
  f.authorize.mockImplementationOnce(async()=>{await pending.promise;return f.permit;});
  const work=f.session.extend!(f.request),rejected=expect(work).rejects.toThrow();
  await f.session.stop({mode:'discard'});pending.release();await rejected;
  expect(f.commands.some(c=>c.type==='extend')).toBe(false);expect(spawn).toHaveBeenCalledOnce();
});

it('settles Stop while an extension acknowledgment is missing and never starts a replacement',async()=>{
  const f=await fixture();f.delayReply();
  const work=f.session.extend!(f.request),rejected=expect(work).rejects.toThrow();
  await new Promise(r=>setImmediate(r));expect(f.commands.some(c=>c.type==='extend')).toBe(true);
  await f.session.stop({mode:'discard'});await rejected;expect(spawn).toHaveBeenCalledOnce();
});
