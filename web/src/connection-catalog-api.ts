import {workspaceFetch} from './workspace-protocol';
import {WORKSPACE_BUILD,WORKSPACE_AUTHENTICATED_BUILD,WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession, workspaceAuthHeaders} from './workspace-auth-headers';
import {parseVendorJson} from './vendor-contract';

export const CONNECTION_IDS = ['core','google','microsoft','scheduling','messaging','payments','portals'] as const;
export type ConnectionId = typeof CONNECTION_IDS[number];
export type ConnectionReadiness = {supported:boolean;setup_allowed:boolean;state:'user_connectable'|'practice_setup'|'coming_soon';runtime_available:boolean;
  installed_account:'not_checked'|'missing'|'installed'|'sandbox_only';client_status:'not_checked';account_status:'not_checked';operation_status:'not_checked';
  actions:{id:string;supported:boolean;runtime_available:boolean}[]};
export type ConnectionCatalog = Record<ConnectionId, boolean> & {readiness?:Record<ConnectionId,ConnectionReadiness>};
const actionIds:Record<ConnectionId,string[]>={core:['practice_connection','visit_discovery','athena_schedule','ehr_write'],
  google:['mail_headers','reviewed_email_source','calendar_source','email_send','calendar_write'],
  microsoft:['mail_headers','calendar_summaries','full_email_source','email_send'],scheduling:['availability','appointment_proposals','live_booking'],
  messaging:['spruce_administrative_message','fax_delivery','reviewed_received_fax'],payments:['sandbox_payment_request','live_payment_collection'],
  portals:['named_portal_work','arbitrary_portal_connection']};
export function parseConnectionCatalog(value:unknown):ConnectionCatalog {
  if(!value || typeof value!=='object' || Array.isArray(value) ||
    Object.keys(value).sort().join(',')!=='services,version')throw new WorkspaceApiError(502);
  const data=value as {version:unknown;services:unknown};
  if(![1,2].includes(data.version as number)||!Array.isArray(data.services)||data.services.length!==CONNECTION_IDS.length)throw new WorkspaceApiError(502);
  const result={} as ConnectionCatalog;
  const readiness={} as Record<ConnectionId,ConnectionReadiness>;
  for(const row of data.services){
    const keys=data.version===1?'id,setup_available':'account_status,actions,client_status,id,installed_account,operation_status,runtime_available,setup_allowed,setup_available,state,supported';
    if(!row||typeof row!=='object'||Object.keys(row).sort().join(',')!==keys||
      !CONNECTION_IDS.includes(row.id)||typeof row.setup_available!=='boolean'||Object.hasOwn(result,row.id))throw new WorkspaceApiError(502);
    result[row.id as ConnectionId]=row.setup_available;
    if(data.version===2){
      if(typeof row.supported!=='boolean'||typeof row.setup_allowed!=='boolean'||typeof row.runtime_available!=='boolean'||
        !['user_connectable','practice_setup','coming_soon'].includes(row.state)||
        !['not_checked','missing','installed','sandbox_only'].includes(row.installed_account)||
        [row.client_status,row.account_status,row.operation_status].some(v=>v!=='not_checked')||
        row.state==='coming_soon'&&row.setup_available||row.setup_available&&!row.setup_allowed||!row.supported&&(row.setup_available||row.runtime_available)||
        !Array.isArray(row.actions)||row.actions.length!==actionIds[row.id as ConnectionId].length)throw new WorkspaceApiError(502);
      for(const [index,action] of row.actions.entries())if(!action||typeof action!=='object'||
        Object.keys(action).sort().join(',')!=='id,runtime_available,supported'||action.id!==actionIds[row.id as ConnectionId][index]||
        typeof action.supported!=='boolean'||typeof action.runtime_available!=='boolean'||!action.supported&&action.runtime_available)throw new WorkspaceApiError(502);
      const {id:_id,setup_available:_setup,...detail}=row;readiness[row.id as ConnectionId]=detail;
    }
  }
  if(data.version===2)result.readiness=readiness;
  return result;
}

export async function readConnectionCatalog(identity:AuthenticatedWorkspaceIdentity, signal:AbortSignal, version:1|2=2):Promise<ConnectionCatalog>{
  const controller=new AbortController(), abort=()=>controller.abort();
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));
  void interrupted.catch(()=>{});
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);
    if(identity.mode!=='desktop_native'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  const timer=setTimeout(abort,15000);signal.addEventListener('abort',abort,{once:true});
  let response:Response|undefined, reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const cancel=(body:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void body?.cancel().catch(()=>{});}catch{/* already closed */}};
  try{
    if(signal.aborted)abort();check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    const headers=await wait(workspaceAuthHeaders(identity,base));check();
    headers.set('X-Cosmas-Connection-Contract',String(version));headers.set('Accept','application/json');
    response=await wait(workspaceFetch(identity,base+'/connections/catalog',{method:'GET',headers,signal:controller.signal,
      credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'}).then(result=>{
      if(controller.signal.aborted){cancel(result.body);throw new WorkspaceApiError(503);}return result;
    }));check();
    if(!response)throw new WorkspaceApiError(503);
    // A legacy server/proxy can still serve exact v1. It remains unqualified
    // configuration evidence rather than being promoted to v2 readiness.
    if(response.status===426&&version===2){cancel(response.body);return await readConnectionCatalog(identity,controller.signal,1);}
    if([401,403,404,426].includes(response.status))throw new WorkspaceApiError(response.status);
    if(response.status!==200||response.redirected||response.headers.has('content-encoding')||
      response.headers.get('content-type')?.split(';',1)[0]!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'))throw new WorkspaceApiError(502);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);
    const bytes=new Uint8Array(version===1?4096:32768);let size=0;
    for(;;){const part=await wait(reader.read());check();if(part.done)break;
      if(part.value.byteLength>bytes.length-size)throw new WorkspaceApiError(502);
      bytes.set(part.value,size);size+=part.value.byteLength;}
    return parseConnectionCatalog(parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,size))));
  }finally{
    clearTimeout(timer);signal.removeEventListener('abort',abort);cancel(reader??response?.body);
    try{reader?.releaseLock();}catch{/* already released */}controller.abort();
  }
}

export function connectionActionClientAvailable(id:string,service?:ConnectionId):boolean{
  // Match actual mount gates and use static env references so the build profile
  // defines apply. Vendor work is compiled without a separate feature flag.
  const google=import.meta.env.VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED==='true';
  const microsoft=import.meta.env.VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED==='true';
  const scheduling=import.meta.env.VITE_WORKSPACE_SCHEDULING_ENABLED==='true';
  const gates:Record<string,boolean>={mail_headers:service==='google'?google:service==='microsoft'?microsoft:google||microsoft,
    calendar_summaries:microsoft,full_email_source:microsoft&&import.meta.env.VITE_MICROSOFT_MESSAGE_ENABLED==='true',reviewed_email_source:google&&import.meta.env.VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED==='true',
    calendar_source:google&&import.meta.env.VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED==='true',
    availability:scheduling,athena_schedule:import.meta.env.VITE_ATHENA_CONNECTION_ENABLED==='true',
    appointment_proposals:scheduling&&import.meta.env.VITE_WORKSPACE_APPOINTMENTS_ENABLED==='true',
    reviewed_received_fax:import.meta.env.VITE_FAX_INBOUND_ENABLED==='true'||import.meta.env.VITE_EFAX_INBOUND_ENABLED==='true',
    sandbox_payment_request:import.meta.env.VITE_FINANCE_WORK_ENABLED==='true',named_portal_work:import.meta.env.VITE_PORTAL_WORK_ENABLED==='true'};
  return WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&(gates[id]??true);
}
