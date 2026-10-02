import {mkdtemp,rm,readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeAll,afterAll,expect,it,vi} from 'vitest';
import {installWorkspaceDesktopCapture} from './workspace-capture-host';
import {NativeProviderPresentation} from './native-provider-presentation';
import {NativeProcessPCMDriver} from './native-process-driver';
import {InMemoryRecordingIndicator} from './recording-indicator';
import {HttpCiphertextUploadTarget} from '../../capture/src/bff/upload-target';
import {MockCaptureService} from '../../capture/src/configured/mock-bff/state';
import {base64UrlDecode,parseEnvelope} from '../../capture/protocol/generated';

// Real renderer and main run in separate global realms. The main-only predicate
// remains intact; generated PCM, native permission/picker and service are fakes.
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const webRequire=createRequire(join(repo,'web/package.json'));
const {JSDOM}=webRequire('jsdom');
type Options=Parameters<typeof installWorkspaceDesktopCapture>[0];
type Handler=Parameters<Options['ipc']['handle']>[1];
const workspaceId='10000000-0000-4000-8000-000000000001',revision='20000000-0000-4000-8000-000000000002';
const cleanup:(()=>Promise<void>|void)[]=[];
let bundle:string,buildDir:string,keys:CryptoKeyPair;
beforeAll(async()=>{
  const {build}=await import(/* @vite-ignore */webRequire.resolve('vite'));
  buildDir=await mkdtemp(join(realpathSync(tmpdir()),'cosmas-recording-renderer-'));
  const virtualEnv={VITE_API_BASE:'app://cosmas/api',VITE_WORKSPACE_DESKTOP_AUTH_ENABLED:'true',
    VITE_DESKTOP_SYNTHETIC_ENABLED:'true',VITE_COSMAS_ENV:'synth_os',VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_WORKSPACE_ENABLED:'true'};
  await build({configFile:false,envDir:false,mode:'test',root:repo,logLevel:'silent',resolve:{alias:{
    'react/jsx-dev-runtime':webRequire.resolve('react/jsx-dev-runtime'),
    'react/jsx-runtime':webRequire.resolve('react/jsx-runtime'),
    'react-dom/client':webRequire.resolve('react-dom/client'),
    'react-dom':webRequire.resolve('react-dom'),
    'react':webRequire.resolve('react'),
    '@cosmaneura-scribe/capture-protocol':join(repo,'clients/capture/protocol/generated.ts'),
    '@cosmaneura-scribe/capacitor-ios-pcm':join(repo,'clients/capture/plugins/ios-pcm/index.ts'),
    '@cosmaneura-scribe/capacitor-secure-queue':join(repo,'clients/capture/plugins/secure-queue/index.ts'),
  }},define:{'process.env.NODE_ENV':JSON.stringify('development'),'import.meta.env':JSON.stringify(virtualEnv),
    ...Object.fromEntries(Object.entries(virtualEnv).map(([key,value])=>['import.meta.env.'+key,JSON.stringify(value)]))},
    esbuild:{jsx:'automatic'},build:{outDir:buildDir,minify:false,lib:{entry:join(repo,'clients/desktop/recorder/recording-operational-renderer.tsx'),
      formats:['iife'],name:'CosmaRecordingLab',fileName:()=> 'renderer.js',cssFileName:'renderer'}}});
  bundle=await readFile(join(buildDir,'renderer.js'),'utf8');
  keys=await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:3072,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['wrapKey','unwrapKey']);
},30000);
afterAll(async()=>{if(buildDir)await rm(buildDir,{recursive:true,force:true});});
afterEach(async()=>{for(const close of cleanup.reverse())await close();cleanup.length=0;vi.restoreAllMocks();});

async function fixture(kind:'in_person'|'telehealth',round:number){
  vi.spyOn(globalThis,'fetch').mockImplementation(async()=>{throw Error('Virtual recording forbids network access');});
  const directory=await mkdtemp(join(realpathSync(tmpdir()),'cosmas-provider-operational-'));
  cleanup.push(()=>rm(directory,{recursive:true,force:true}));
  const sessionId=crypto.randomUUID(),service=new MockCaptureService({sessionId});
  // Fixture ingest family accepts only in-person initialization; actual fresh
  // UI admission below separately validates the selected virtual modality.
  const modality='in_person';
  const person={appointment_id:'invented-walk-in',practitioner_id:'invented-family-physician',patient_id:'invented-patient'};
  const consent=service.createConsent({...person,participant_regions:['US-NY'],modality,method:'verbal_attestation',
    all_parties_consented:true,granted_at:new Date().toISOString()},'consent');
  const session=service.createSession({...person,consent_record_id:consent.id,modality},'session');
  let sessionStatus=session.status,wrappedDek='',frames=0,active=false;
  const steps:unknown[]=[],events:unknown[]=[],expected:number[]=[],reservations=new Map<string,{sequence:number;aad:string}>();
  const startedAt=performance.now();
  const recordEvent=(event:Record<string,unknown>)=>events.push({...event,elapsed_ms:performance.now()-startedAt});
  const uploads=new Map<string,Uint8Array>(),calls:{kind:string;key:string;payload:unknown}[]=[];
  const publicJwk=await crypto.subtle.exportKey('jwk',keys.publicKey);
  const request=async(request:Request)=>{
    expect(request.headers.get('X-Cosmas-Desktop-Session')).toBe(revision);
    if(new URL(request.url).pathname==='/api/provider-team/identity')return Response.json({contract_version:1,box_id:workspaceId,
      actor_id:'30000000-0000-4000-8000-000000000003',recovery_scope:'a'.repeat(64)});
    const body=await request.json(),op=body.operation,key=body.idempotency_key;
    expect(body.session_id).toBe(session.id);calls.push({kind:op.kind,key,payload:op.payload});let receipt:unknown;
    switch(op.kind){
      case 'creator_review':receipt={schema_version:'1.0',session_id:session.id,status:sessionStatus,source:null,working:null,review_queue:null};break;
      case 'capabilities':receipt={...service.capabilities(),max_chunks:2048,remaining_aggregate_plaintext_bytes:402653184};break;
      case 'encryption_key':receipt={...service.audioEncryptionKey(),public_jwk:{...publicJwk,key_ops:['wrapKey']}};break;
      case 'bind_key':wrappedDek=op.payload.wrapped_dek;receipt=service.bindSessionAudioKey(session.id,op.payload,key);break;
      case 'issue_lease':receipt=service.issueLease(op.payload,key);break;
      case 'renew_lease':receipt=service.renewLease(op.lease_id,op.payload,key);break;
      case 'reserve_chunks':{
        const value=service.reserveChunks(op.payload,key);receipt=value;
        for(const r of value.reservations)reservations.set(r.object_id,{sequence:r.sequence_number,aad:r.additional_authenticated_data});break;}
      case 'authorize_upload':receipt=service.authorizeUpload(op.object_id,op.payload,key);break;
      case 'chunk_receipt':receipt=service.chunkReceipt(op.object_id);break;
      case 'register_chunk':receipt=service.registerChunk(op.payload,key);break;
      case 'complete':receipt=service.completeCapture(op.payload,key);sessionStatus='uploaded';break;
      default:throw Error('Unexpected operation '+op.kind);
    }
    return Response.json({workspace_id:workspaceId,session_id:session.id,operation:op.kind,receipt});
  };
  vi.spyOn(HttpCiphertextUploadTarget.prototype,'putCompleteEnvelope').mockImplementation(async(url,envelope)=>{
    const parsed=new URL(url),id=parsed.pathname.split('/').at(-1)!;
    uploads.set(id,envelope.slice());service.putEnvelope(id,parsed.searchParams.get('receipt')!,envelope);
  });
  const indicator=new InMemoryRecordingIndicator();
  vi.spyOn(NativeProviderPresentation,'open').mockResolvedValue({publish:indicator.publish.bind(indicator),selectWindow:async()=>
    ({application:'com.google.Chrome',processID:1,windowID:1}),dispose:async()=>{},onEvent:()=>()=>{}} as unknown as NativeProviderPresentation);
  vi.spyOn(NativeProcessPCMDriver.prototype,'getAvailability').mockResolvedValue(true);
  let emit: (count:number)=>Promise<void>=async()=>{throw Error('Source inactive');};
  vi.spyOn(NativeProcessPCMDriver.prototype,'start').mockImplementation((_configuration,sink)=>{
    const mark={hostTimeNanoseconds:'1000000000',microphonePrerollNanoseconds:'0',systemPrerollNanoseconds:'0'};
    let localFrames=0;
    emit=async(count)=>{
      expect(active).toBe(true);const began=performance.now();
      for(let offset=0;offset<count;offset+=4000){
        const size=Math.min(4000,count-offset),bytes=new Uint8Array(size*2),view=new DataView(bytes.buffer);
        for(let i=0;i<size;i++){
          const mic=Math.round(1800*Math.sin(2*Math.PI*220*(frames+i)/16000));
          const remote=kind==='telehealth'?Math.round(1000*Math.sin(2*Math.PI*440*(frames+i)/16000)):0;
          const sample=(mic+remote)||0;view.setInt16(i*2,sample,true);expected.push(sample);
        }
        const firstFrame=localFrames;localFrames+=size;frames+=size;
        await sink.onPcmPacket({firstFrame,pcmBytes:bytes});
      }
      recordEvent({event:'generated_pcm_accepted',frames:count,delivery_ms:performance.now()-began});
    };
    return {ready:Promise.resolve(mark),activate:()=>{active=true;recordEvent({event:'source_activated'});},stop:async({mode})=>{
      active=false;recordEvent({event:'source_stopped',mode,frames:localFrames});
      return mode==='discard'?null:{start:mark,endHostTimeNanoseconds:String(1_000_000_000+localFrames*62_500),outputFrames:localFrames,
        microphoneTailNanoseconds:'0',systemTailNanoseconds:'0'};
    }};
  });
  let grant:Record<string,unknown>={};
  const sourceRequest=async(method:string,payload:Record<string,unknown>)=>{
    if(method==='sourcePrepare'){
      grant={captureSessionId:session.id,actorId:person.practitioner_id,consentRecordId:consent.id,consentStatus:'granted',
        sessionStatus:'authorized',source:'desktop_companion',sourceLeaseId:crypto.randomUUID()};
      return {grant,processFence:{epoch:crypto.randomUUID(),coordinatorDevice:'1',coordinatorInode:'1',captureDevice:'1',captureInode:'2'}};
    }
    if(method==='sourceAuthorize'){
      expect(payload.sourceLeaseId).toBe(grant.sourceLeaseId);const expiresAt=new Date(Date.now()+15000).toISOString();
      return {schemaVersion:1,decision:'authorized',...grant,issuedAt:new Date().toISOString(),expiresAt,
        captureCapability:{capabilityId:crypto.randomUUID(),secret:'invented-private-capability',expiresAt}};
    }
    return null;
  };
  const handlers=new Map<string,Handler>(),listeners=new Set<(value:unknown)=>void>();
  const frame={url:'app://cosmas/index.html'},event={sender:{id:7,mainFrame:frame},senderFrame:frame};
  const messages:unknown[]=[];
  const renderer={id:7,mainFrame:frame,isDestroyed:()=>false,send:(_channel:string,value:unknown)=>{
    messages.push(structuredClone(value));for(const listener of listeners)listener(structuredClone(value));},on:()=>{},removeListener:()=>{}};
  const options:Options={auth:{getState:async()=>({phase:'ready',revision}),snapshot:()=>({phase:'ready',revision}),sourceRequest,subscribe:()=>()=>{}},
    ipc:{handle:(name,fn)=>{handlers.set(name,fn);},removeHandler:name=>{handlers.delete(name);}},renderer,directory,
    apiOrigin:'https://cosmas.invalid',uploadOrigins:['http://127.0.0.1:4174'],request,isSessionActive:()=>true,
    protection:{isEncryptionAvailable:()=>true,encryptString:value=>Buffer.from(value),decryptString:value=>value.toString()},
    audio:{helperPath:'/unused-invented-audio',helperSha256:'0'.repeat(64)},presentation:{helperPath:'/unused-invented-indicator',helperSha256:'0'.repeat(64)}};
  let host=installWorkspaceDesktopCapture(options);cleanup.push(()=>host.close());
  const admissions:unknown[]=[];
  const dom=new JSDOM('<!doctype html><html><body></body></html>',{url:'app://cosmas/index.html',runScripts:'outside-only'});
  cleanup.push(()=>dom.window.close());
  class SyntheticMessageChannel {
    readonly port1={onmessage:null as (()=>void)|null};
    readonly port2={postMessage:()=>setTimeout(()=>this.port1.onmessage?.(),0)};
  }
  Object.assign(dom.window,{TextEncoder,TextDecoder,Request,Response,Headers,AbortController,AbortSignal,MessageChannel:SyntheticMessageChannel,
    structuredClone, __recordingLab:{workspaceId,sessionId:session.id,revision,round,
      open:(value:unknown)=>handlers.get('cosmas:workspace-capture:open:v1')!(event,structuredClone(value)),
      request:(value:unknown)=>handlers.get('scribe:provider:recorder:v1')!(event,structuredClone(value)),
      subscribe:(listener:(value:unknown)=>void)=>{listeners.add(listener);return()=>listeners.delete(listener);},
      fetch:async(input:unknown,init:RequestInit)=>{
        expect(String(input)).toBe('app://cosmas/api/workspaces/'+workspaceId+'/capture/admission');
        const body=JSON.parse(String(init.body));admissions.push(body);
        if(!body.attestation&&admissions.length===1)return Response.json({detail:'capture_consent_required'},{status:409,headers:{'Cache-Control':'no-store'}});
        if(body.attestation){
          expect(body.attestation.all_parties_consented).toBe(true);expect(body.attestation.modality).toBe('virtual');
          expect(Object.keys(body.attestation).sort()).toEqual(['all_parties_consented','granted_at','method','modality','participant_regions']);
        }
        return Response.json({status:'prepared',workspace_id:workspaceId,session_id:session.id,consent_record_id:consent.id,
          configured_capture:{schema_version:'1.0',language_mode:'en-US'}},
          {headers:{'Cache-Control':'no-store'}});
      },emit:(count:number)=>emit(count),reopen:async()=>{await host.close();host=installWorkspaceDesktopCapture(options);},
      capture:(label:string,value:unknown)=>{if(label==='ui_step')steps.push(value);else recordEvent({event:label,value});}}});
  dom.window.eval(bundle);
  return {run:()=>dom.window.runRecordingScenario(),async verify(){
    expect(calls.filter(c=>c.kind==='complete')).toHaveLength(1);
    expect(calls.filter(c=>c.kind==='bind_key')).toHaveLength(1);
    expect(uploads.size).toBe(3);
    const key=await crypto.subtle.unwrapKey('raw',new Uint8Array(base64UrlDecode(wrappedDek)),keys.privateKey,{name:'RSA-OAEP'},
      {name:'AES-GCM',length:256},false,['decrypt']);
    const actual:number[]=[];
    for(const [id,envelope] of [...uploads].sort(([a],[b])=>reservations.get(a)!.sequence-reservations.get(b)!.sequence)){
      const reserved=reservations.get(id)!,parsed=parseEnvelope(envelope);
      const bytes=new Uint8Array(await crypto.subtle.decrypt({name:'AES-GCM',iv:new Uint8Array(base64UrlDecode(parsed.header.nonce)),
        additionalData:new Uint8Array(base64UrlDecode(reserved.aad))},key,new Uint8Array(parsed.ciphertext)));
      expect(Buffer.from(bytes.subarray(0,4)).toString()).toBe('RIFF');
      const wav=new DataView(bytes.buffer);expect(wav.getUint32(24,true)).toBe(16000);expect(wav.getUint16(22,true)).toBe(1);
      expect(wav.getUint32(40,true)+44).toBe(bytes.length);
      for(let offset=44;offset<bytes.length;offset+=2)actual.push(wav.getInt16(offset,true));
    }
    expect(actual).toEqual(expected);expect(actual.length).toBe(336000);
    const dir=join(directory,'native-recordings');
    for(const name of (await readdir(dir)).filter(name=>name.endsWith('.sqlite'))){
      expect((await readFile(join(dir,name))).includes(Buffer.from(new Int16Array(expected.slice(0,128)).buffer))).toBe(false);
    }
    expect(JSON.stringify(messages)).not.toMatch(/invented-private-capability|wrapped_dek|pcmBytes|windowID|helperPath|processFence/);
    const pcm=Buffer.from(new Int16Array(actual).buffer);
    return {schema_version:1,status:'passed',scenario:kind,round,persona:'Nontechnical family-practice physician',
      operational_flow:'Actual React CapturePanel buttons → fixed desktop recorder view → main workspace host → PCM capture/encryption → encrypted SQLite → upload receipt',
      audio:{frames:actual.length,duration_seconds:actual.length/16000,channels:1,sample_rate_hz:16000,
        pcm_sha256:createHash('sha256').update(pcm).digest('hex'),exact_generated_pcm_match:true,tail_frames:16000,uploaded_chunks:uploads.size},
      dob_optional:true,consent_required:true,complete_calls:1,binding_calls:1,steps,events,
      acceptance:{simulated_persona:true,feedback:['Record visit is visible and consent starts recording with one clear action.',
        'Pause asks me to Prepare to resume and then press Start; both actions worked and never silently resumed.',
        round===1?'Recovery retained my saved audio and offered Finish this recording; the final UI said Audio uploaded.':
          'Stop and upload completed the visit and showed Audio uploaded.'],
        limits:'A scripted persona exercising DOM controls is not observed acceptance by a real clinician.'},
      boundaries:['Generated mixed PCM enters at the native driver sink; no physical microphone, Zoom, permissions or hardware.',
        'In-person scenario uses silent system channel through desktop companion; bare microphone selection is a separate qualification.',
        'Native picker, protection/custody and backend admission/upload receiver are synthetic; no real credentials, speech recognition or patient data.',
        'DOM confirms state text/control dispatch. jsdom does not prove Electron paint, OS selection or physical-device usability.']};
  }};
}

it.each([['in_person',1],['telehealth',1],['in_person',2],['telehealth',2]] as const)(
  'operational recording: nontechnical provider completes %s round %s through actual UI with exact saved audio',async(kind,round)=>{
    const f=await fixture(kind,round);await f.run();const evidence=await f.verify();
    if(process.env.COSMABOT_RECORDING_EVIDENCE_DIR){
      const out=resolve(process.env.COSMABOT_RECORDING_EVIDENCE_DIR,'desktop');await mkdir(out,{recursive:true});
      await writeFile(join(out,kind+'-round-'+round+'.json'),JSON.stringify(evidence,null,2)+'\n');
    }
  },30000);
