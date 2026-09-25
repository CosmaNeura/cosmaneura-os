const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ORIGIN=/^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const CALLBACK='/connections/microsoft/callback';
export function microsoftNavigationConfig(tenantId='',clientId='',callbackUri='') {
  if(tenantId===''&&clientId===''&&callbackUri==='')return null;
  if(typeof tenantId!=='string'||!UUID.test(tenantId)||typeof clientId!=='string'||!UUID.test(clientId)||typeof callbackUri!=='string'||
    callbackUri.length>512||!callbackUri.endsWith(CALLBACK)||!ORIGIN.test(callbackUri.slice(0,-CALLBACK.length)))throw new Error('Microsoft navigation unavailable');
  return Object.freeze({tenantId,clientId,callbackUri});
}
export function validMicrosoftNavigationUrl(href,config) {
  if(!config||typeof href!=='string'||href.length>4096||/[\u0000-\u0020\u007f]/.test(href))return false;
  try{
    const base=`https://login.microsoftonline.com/${config.tenantId}/oauth2/v2.0/authorize`;
    if(!href.startsWith(base+'?'))return false;
    const url=new URL(href),q=url.searchParams;
    const fields=['client_id','code_challenge','code_challenge_method','prompt','redirect_uri','response_mode','response_type','scope','state'];
    return url.origin==='https://login.microsoftonline.com'&&url.pathname===`/${config.tenantId}/oauth2/v2.0/authorize`&&!url.username&&!url.password&&!url.hash&&
      [...q.keys()].sort().join(',')===fields.join(',')&&fields.every(k=>q.getAll(k).length===1)&&
      q.get('client_id')===config.clientId&&q.get('redirect_uri')===config.callbackUri&&q.get('response_type')==='code'&&q.get('response_mode')==='query'&&
      q.get('scope')==='offline_access User.Read Mail.Read Calendars.Read'&&q.get('prompt')==='select_account'&&q.get('code_challenge_method')==='S256'&&
      ['state','code_challenge'].every(k=>/^[A-Za-z0-9_-]{43}$/.test(q.get(k)||''));
  }catch{return false;}
}
