// Only the isolated UX lab aliases these service calls. No network or real data.
import athena from '../src/__fixtures__/athena-connection.json';
import {WorkspaceApiError} from '../src/workspace-api';
import type {MicrosoftAction,MicrosoftStatus,MicrosoftView} from '../src/microsoft-connection-api';
export {MICROSOFT_CONNECTION_BUILD,validMicrosoftAuthorizationUrl,validateMicrosoftResponse} from '../src/microsoft-connection-api';
let failNext=false;
export const failNextRead=()=>{failNext=true;};
const account={label:'Cedar demonstration practice',email:'cedar@example.invalid'};
export const providerRequests:string[]=[];
async function wait(signal?:AbortSignal){
  await new Promise<void>((resolve,reject)=>{
    const abort=()=>{clearTimeout(timer);reject(new WorkspaceApiError(503));};
    const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},120);
    signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  });
}
export async function microsoftConnectionRequest(_identity:unknown,action:MicrosoftAction,signal?:AbortSignal):Promise<MicrosoftStatus|MicrosoftView|{state:'disconnected'}>{
  providerRequests.push(action);await wait(signal);
  if(action==='disconnect')return {state:'disconnected'};
  if(action==='start')throw new WorkspaceApiError(404);
  if(action==='status')return {state:'connected',account,connected_at:'2026-10-25T10:00:00Z'};
  if(failNext){failNext=false;throw new WorkspaceApiError(503);}
  const common={account,more:false,observed_at:'2026-10-25T15:00:00Z'};
  return action==='mail'?{...common,kind:'mail',items:[{id:'invented-mail',subject:'Invented appointment question',sender:'example@example.invalid',received_at:'2026-10-25T12:00:00Z',is_read:false}]}:
    {...common,kind:'calendar',items:[{id:'invented-calendar',subject:'Invented team planning',starts_at:'2026-10-26T13:00:00Z',ends_at:'2026-10-26T13:30:00Z',cancelled:false,all_day:false}]};
}
export const coreConnectionApi={read:async(_identity:unknown,command:{action:string},signal?:AbortSignal)=>{
  providerRequests.push(command.action);await wait(signal);
  if(failNext){failNext=false;throw new WorkspaceApiError(503);}
  if(command.action==='athena_connection')return structuredClone(athena.connection.response);
  if(command.action==='athena_appointments')return structuredClone(athena.appointments.response);
  throw new WorkspaceApiError(404);
}};
