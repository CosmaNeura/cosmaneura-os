// Isolated UI fixtures. No authentication, provider calls or saved user data.
export let scenario='mixed';
export const setScenario=(value:string)=>{scenario=value;};
export const accountStatusSupported=(id:string)=>['core','google','microsoft','scheduling'].includes(id);
const wait=(signal:AbortSignal)=>new Promise<void>((resolve,reject)=>{
  const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},scenario==='slow'?5000:350);
  const abort=()=>{clearTimeout(timer);reject(new Error('aborted'));};
  signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
});
export async function readConnectionCatalog(_identity:unknown,signal:AbortSignal){
  await wait(signal);if(scenario==='offline')throw new Error('Synthetic offline fixture');
  return {core:true,google:true,microsoft:true,scheduling:false,messaging:false,payments:false,portals:false};
}
export async function readConnectionSummary(_identity:unknown,id:string,signal:AbortSignal){
  await wait(signal);
  if(scenario==='failure'&&id==='microsoft')throw new Error('Synthetic status failure');
  if(scenario==='new')return {label:'Not connected',reason:'Sign in to connect your account.',action:'Connect account',tone:'attention',checkedAt:Date.now()};
  if(id==='microsoft')return {label:'Sign-in pending',reason:'Continue sign-in, then return to check the result.',action:'Continue setup',tone:'attention',checkedAt:Date.now()};
  return {label:'Connected',reason:id==='core'?'Cedar synthetic practice':'provider@example.invalid',action:'View connection',tone:'ready',checkedAt:Date.now()};
}
