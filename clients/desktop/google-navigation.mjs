const CLIENT = /^[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com$/;
const ORIGIN = /^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const CALLBACK = '/connections/google/callback';
export function googleNavigationConfig(clientId='', callbackUri='') {
  if(clientId===''&&callbackUri==='')return null;
  if(typeof clientId!=='string'||!CLIENT.test(clientId)||typeof callbackUri!=='string'||
      !callbackUri.endsWith(CALLBACK)||!ORIGIN.test(callbackUri.slice(0,-CALLBACK.length)))throw new Error('Google navigation unavailable');
  return Object.freeze({clientId,callbackUri});
}
export function validGoogleNavigationUrl(href,config) {
  if(!config||typeof href!=='string'||href.length>4096||!href.startsWith('https://accounts.google.com/o/oauth2/v2/auth?')||/[\u0000-\u0020\u007f]/.test(href))return false;
  try{
    const url=new URL(href),q=url.searchParams;
    if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth'||url.username||url.password||url.hash)return false;
    const required=['access_type','client_id','code_challenge','code_challenge_method','include_granted_scopes','prompt','redirect_uri','response_type','scope','state'];
    return [...q.keys()].sort().join(',')===required.join(',')&&required.every(k=>q.getAll(k).length===1)&&
      q.get('client_id')===config.clientId&&q.get('redirect_uri')===config.callbackUri&&q.get('response_type')==='code'&&
      q.get('scope')==='openid email https://www.googleapis.com/auth/gmail.metadata'&&q.get('access_type')==='offline'&&q.get('prompt')==='consent select_account'&&
      q.get('include_granted_scopes')==='false'&&q.get('code_challenge_method')==='S256'&&['state','code_challenge'].every(k=>/^[A-Za-z0-9_-]{43}$/.test(q.get(k)||''));
  }catch{return false;}
}
