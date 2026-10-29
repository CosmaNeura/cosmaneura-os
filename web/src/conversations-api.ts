import {assertCurrentDesktopSession,workspaceAuthHeaders} from './workspace-auth-headers';
import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type BotRole} from './workspace-api';
import {parseVendorJson,vendorObject} from './vendor-contract';
import {teamAddress,teamUuid} from './team-setup-request';

export type ConversationSummary={workspace_id:string;appointment_id:string|null;context_label:string;
  bot:{address:string;role:BotRole;name:string;available:boolean};preview:string;preview_withheld:boolean;
  attention:'idle'|'working'|'needs_review'|'needs_check';last_activity_at:string;watermark:string;
  unread:boolean;manual_unread:boolean;marker_version:number};
export type ConversationInbox={contract_version:1;as_of:string;rows:ConversationSummary[];next_cursor:string|null};
export type ConversationRead={contract_version:1;marker_version:number;manual_unread:boolean;seen_watermark:string|null};
export type ReadMarkerCommand={watermark?:string;manual_unread?:boolean;expected_version?:number};
const watermark=(value:unknown):value is string=>typeof value==='string'&&/^r1[0-9a-f]{16}[a-z][0-9a-f]{96}$/.test(value);
const cursor=(value:unknown):value is string=>typeof value==='string'&&/^c1[0-9a-f]{160}$/.test(value);
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>vendorObject(value)&&Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
const invalid=():never=>{throw new WorkspaceApiError(502);};
export function validateConversationInbox(value:unknown):ConversationInbox {
  if(!closed(value,'contract_version,as_of,rows,next_cursor')||value.contract_version!==1||typeof value.as_of!=='string'||!Number.isFinite(Date.parse(value.as_of))||!Array.isArray(value.rows)||value.rows.length>20||value.next_cursor!==null&&!cursor(value.next_cursor))return invalid();
  const seen=new Set<string>();
  for(const row of value.rows){
    if(!closed(row,'workspace_id,appointment_id,context_label,bot,preview,preview_withheld,attention,last_activity_at,watermark,unread,manual_unread,marker_version')||!teamUuid(row.workspace_id)||row.appointment_id!==null&&!teamUuid(row.appointment_id)||typeof row.context_label!=='string'||!row.context_label.trim()||row.context_label.length>200||
      !closed(row.bot,'address,role,name,available')||!teamAddress(row.bot.address)||!['scribe','visit_prep','follow_up','chief','custom','research'].includes(String(row.bot.role))||typeof row.bot.name!=='string'||!row.bot.name.trim()||row.bot.name.length>40||typeof row.bot.available!=='boolean'||
      typeof row.preview!=='string'||row.preview.length>180||typeof row.preview_withheld!=='boolean'||!['idle','working','needs_review','needs_check'].includes(String(row.attention))||typeof row.last_activity_at!=='string'||!Number.isFinite(Date.parse(row.last_activity_at))||!watermark(row.watermark)||typeof row.unread!=='boolean'||typeof row.manual_unread!=='boolean'||!Number.isSafeInteger(row.marker_version)||Number(row.marker_version)<0)return invalid();
    const key=`${row.workspace_id}:${row.bot.address}`;if(seen.has(key))return invalid();seen.add(key);
  }
  return value as ConversationInbox;
}
function validateRead(value:unknown):ConversationRead {
  if(!closed(value,'contract_version,marker_version,manual_unread,seen_watermark')||value.contract_version!==1||!Number.isSafeInteger(value.marker_version)||Number(value.marker_version)<1||typeof value.manual_unread!=='boolean'||value.seen_watermark!==null&&!watermark(value.seen_watermark))return invalid();
  return value as ConversationRead;
}
async function request(identity:AuthenticatedWorkspaceIdentity,path:string,signal?:AbortSignal,body?:ReadMarkerCommand):Promise<unknown>{
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  const controller=new AbortController(),cancel=()=>controller.abort(),timer=setTimeout(cancel,15000);
  signal?.addEventListener('abort',cancel,{once:true});if(signal?.aborted)cancel();
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));
  void interrupted.catch(()=>{});
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  try{
    check();const headers=await wait(workspaceAuthHeaders(identity,base));check();headers.set('X-Cosmas-Conversations','1');
    const response=await wait(workspaceFetch(identity,base+path,{method:body?'POST':'GET',headers,...(body?{body:JSON.stringify(body)}:{}),signal:controller.signal,credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'}));check();
    if(!response.ok)throw new WorkspaceApiError(response.status);
    const length=response.headers.get('content-length');
    if(response.redirected||response.headers.get('content-type')?.split(';',1)[0].trim()!=='application/json'||response.headers.has('content-encoding')||!response.headers.get('cache-control')?.split(',').some(value=>value.trim()==='no-store')||length!==null&&(!/^\d+$/.test(length)||Number(length)>65536))return invalid();
    reader=response.body?.getReader();if(!reader)return invalid();const chunks:Uint8Array[]=[];let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;if(size>65536)return invalid();chunks.push(part.value);}
    if(length!==null&&size!==Number(length))return invalid();const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.length;}
    return parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
  }catch(cause){if(cause instanceof WorkspaceApiError)throw cause;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',cancel);try{void reader?.cancel().catch(()=>{});reader?.releaseLock();}catch{/* The next read remains explicit. */}controller.abort();}
}
export const conversationsApi={
  read:async(identity:AuthenticatedWorkspaceIdentity,page:string|null=null,signal?:AbortSignal)=>{if(page!==null&&!cursor(page))throw new WorkspaceApiError(422);return validateConversationInbox(await request(identity,'/workspaces/conversations'+(page?'/pages/'+page:''),signal));},
  mark:async(identity:AuthenticatedWorkspaceIdentity,wid:string,bot:string,command:ReadMarkerCommand={},signal?:AbortSignal)=>{
    if(!teamUuid(wid)||!teamAddress(bot)||!vendorObject(command)||Object.keys(command).some(key=>!['watermark','manual_unread','expected_version'].includes(key))||command.watermark!==undefined&&!watermark(command.watermark)||(command.manual_unread===undefined)!==(command.expected_version===undefined)||command.manual_unread!==undefined&&(typeof command.manual_unread!=='boolean'||!Number.isSafeInteger(command.expected_version)||command.expected_version!<0)||command.manual_unread===false&&!command.watermark)throw new WorkspaceApiError(422);
    return validateRead(await request(identity,`/workspaces/${wid}/conversations/${bot}/read`,signal,command));},
};
