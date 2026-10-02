export const isModelActivityPath = path => /^\/provider-team\/activity\/(?:attention|recent)(?:\/a1[0-9a-f]{128})?$/.test(path);
// These are Cosmas routes, never vendor hosts or renderer-selected destinations.
const ID = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}';
const vendor = new RegExp(`^/workspaces/${ID}/vendor-work(?:/(${ID})(?:/(observations|decide|withdraw|publish|submit|reconcile|result|verify|retire))?|/(options|resolve))?$`);
const artifact = new RegExp(`^/workspaces/${ID}/vendor-artifacts(?:/(${ID})/content|/(resolve))?$`);
const vendorPreparation = new RegExp(`^/workspaces/${ID}/vendor-preparations/retire$`);
const finance = new RegExp(`^/workspaces/${ID}/finance-work(?:/(${ID})(?:/(observations|decide|withdraw|submit|reconcile|result|verify))?|/(options|resolve))?$`);
const financeSetup = new RegExp(`^/finance-setup(?:/(${ID})(?:/(history))?|/(propose_account|propose_customer|activate|disable|revoke|resolve))?$`);
const vendorSetup = new RegExp(`^/vendor-settings(?:/(${ID})(?:/(history))?|/(propose_account|propose_recipient|activate|disable|revoke|resolve))?$`);
const portal = new RegExp(`^/portal-setup(?:/(${ID})(?:/(history))?|/(propose|activate|disable|revoke|resolve))?$`);
const portalWork = new RegExp(`^/workspaces/${ID}/portal-work(?:/(${ID})(?:/(observations|decide|withdraw|submit|status|result|verify))?|/(resolve))?$`);
const membershipSavedFinance = new RegExp(`^/workspaces/${ID}/membership-work/${ID}/results/${ID}/finance-evidence$`);
const membership = new RegExp(`^/workspaces/${ID}/membership-work(?:/(${ID})(?:/(history|decide|result|verify|withdraw))?|/(options|resolve|retire))?$`);
const staff = new RegExp(`^/practice-work(?:/(pages/${ID}|${ID})(?:/(handoffs|result|vendor-command/resolve))?)?$`);
const inbox = new RegExp(`^/inbox/(${ID})(?:/(history|review-options|review|triage|result|verify)|/sources/(${ID}))?$`);
const inboxHandoff = new RegExp(`^/inbox-handoffs/(${ID})(?:/(decide|handoff|result|verify|resolve))?$`);
const inboxProposal = new RegExp(`^/workspaces/${ID}/inbox-handoffs/(propose|resolve)$`);
const coreRecordLocation = new RegExp(`^/workspaces/${ID}/cosmaneura-record/location$`);
const research = new RegExp(`^/workspaces/${ID}/research(?:/(saved|search|resolve|${ID}/save(?:/resolve)?))?$`);
const googleCalendarReview = new RegExp(`^/workspaces/${ID}/google-calendar/review$`);
const googleMessageReview = new RegExp(`^/workspaces/${ID}/google-messages/review$`);
export const CONNECTOR_HEADERS = ['X-Cosmas-Vendor-Contract','X-Cosmas-Finance-Contract','X-Cosmas-Portal-Contract','X-Cosmas-Portal-Work-Contract','X-Cosmas-Finance-Setup-Contract','X-Cosmas-Membership-Contract','X-Cosmas-Vendor-Setup-Contract','X-Cosmas-Inbox-Contract','X-Cosmas-Inbox-Handoff-Contract','X-Cosmas-Record-Contract','X-Cosmas-Research-Contract','X-Cosmas-Connection-Contract','X-Cosmas-Scheduling-Login','X-Cosmas-Microsoft-Connection','X-Cosmas-Google-Connection','X-Cosmas-Practice-Access-Contract','X-Cosmas-Google-Messages','X-Cosmas-Google-Calendar'];

/** Closed method/path/query classification, shared by admission and byte budgets. */
export function connectorApiRoute(target, method) {
  const question = target.indexOf('?'), path = question < 0 ? target : target.slice(0,question);
  const query = question < 0 ? '' : target.slice(question);
  const plan = (header,input,output,extra={}) => ({header,input,output,seconds:30,...extra});
  const incoming = (header,input,output) => plan(header,input,output,{seconds:15,strictResponse:true,errorOutput:2048});
  if(path === '/connections/google/calendar-summaries' || googleCalendarReview.test(path)) return method === 'POST' && !query
    ? plan('X-Cosmas-Google-Calendar',4096,googleCalendarReview.test(path)?12000000:131072,{seconds:50,strictResponse:true,errorOutput:2048}) : null;
  if(path === '/connections/google/messages' || googleMessageReview.test(path)) return method === 'POST' && !query
    ? plan('X-Cosmas-Google-Messages',4096,googleMessageReview.test(path)?12000000:131072,{seconds:50,strictResponse:true,errorOutput:2048}) : null;
  if(path === '/connections/catalog') return method === 'GET' && !query
    ? incoming(CONNECTOR_HEADERS[11],0,4096) : null;
  if(path === '/vendor-settings/readiness') return method === 'GET' && !query
    ? plan(CONNECTOR_HEADERS[6],0,4096,{seconds:15}) : null;
  if(vendorPreparation.test(path)) return method==='POST'&&!query ? plan(CONNECTOR_HEADERS[0],33792,16384) : null;
  if(path==='/practice-access/compatibility')
    return method==='GET' && !query ? incoming(CONNECTOR_HEADERS[15],0,4096) : null;
  if(path==='/practice-access' || path==='/practice-access/requests')
    return method==='GET' && !query ? incoming(CONNECTOR_HEADERS[15],0,131072) : null;
  if(['/practice-access/request','/practice-access/cancel','/practice-access/decide','/practice-access/members','/practice-access/member-change'].includes(path))
    return method==='POST' && !query ? incoming(CONNECTOR_HEADERS[15],4096,131072) : null;
  if(path === '/connections/google/session') return method === 'POST' && !query
    ? plan(CONNECTOR_HEADERS[14],1024,131072,{seconds:50,strictResponse:true,errorOutput:2048}) : null;
  if(path === '/connections/microsoft/session') return method === 'POST' && !query
    ? plan(CONNECTOR_HEADERS[13],1024,131072,{seconds:50,strictResponse:true,errorOutput:2048}) : null;
  if(path === '/connections/scheduling/session') return method === 'POST' && !query
    ? plan(CONNECTOR_HEADERS[12],2048,69632,{seconds:25,strictResponse:true,errorOutput:2048}) : null;
  if(path === '/connections/cosmaneura/read') return method === 'POST' && !query
    ? plan(CONNECTOR_HEADERS[11],2048,69632,{seconds:35,strictResponse:true,errorOutput:2048}) : null;
  if(path === '/research/catalog') return method === 'GET' && !query ? plan(CONNECTOR_HEADERS[10],0,131072,{seconds:35,strictResponse:true,errorOutput:2048}) : null;
  const researchMatch=research.exec(path);
  if(researchMatch){
    if(!researchMatch[1]||researchMatch[1]==='saved')return method==='GET'&&new RegExp(`^\\?bot=${ID}(?:&before=${ID})?$`).test(query)?plan(CONNECTOR_HEADERS[10],0,researchMatch[1]==='saved'?131072:1048576,{seconds:35,strictResponse:true,canonicalQuery:true,errorOutput:2048}):null;
    return method==='POST'&&!query?plan(CONNECTOR_HEADERS[10],8192,131072,{seconds:35,strictResponse:true,errorOutput:2048}):null;
  }
  // Incoming source reads and internal handoffs grant no vendor send/read-state API.
  if (!query) {
    if (coreRecordLocation.test(path)) return method === 'GET'
      ? plan(CONNECTOR_HEADERS[9],0,2048,{seconds:35,strictResponse:true,errorOutput:2048}) : null;
    if (path === '/inbox' && method === 'GET') return incoming(CONNECTOR_HEADERS[7],0,131072);
    if (path === '/inbox/resolve' && method === 'POST') return incoming(CONNECTOR_HEADERS[7],8192,8192);
    const item = inbox.exec(path);
    if (item) {
      const [, ,action,source] = item;
      if (method === 'GET' && (!action || action === 'history' || action === 'review-options'))
        return incoming(CONNECTOR_HEADERS[7],0,action === 'history' ? 2097152 : action === 'review-options' ? 131072 : 65536);
      if (method === 'POST' && !source && ['review','triage','result','verify'].includes(action))
        return incoming(CONNECTOR_HEADERS[7],8192,8192);
      return null;
    }
    if (path === '/inbox-handoffs' && method === 'GET') return incoming(CONNECTOR_HEADERS[8],0,131072);
    if (inboxProposal.test(path) && method === 'POST') return incoming(CONNECTOR_HEADERS[8],8192,16384);
    const work = inboxHandoff.exec(path);
    if (work) {
      if (method === 'GET' && !work[2]) return incoming(CONNECTOR_HEADERS[8],0,65536);
      if (method === 'POST' && work[2]) return incoming(CONNECTOR_HEADERS[8],8192,16384);
      return null;
    }
  }
  const page = () => {
    if (!query) return true;
    const params = new URLSearchParams(query), values = [...params.entries()];
    return values.length === 1 && values[0][0] === 'cursor' && /^[\x21-\x7e]{1,512}$/.test(values[0][1]) &&
      query === '?cursor=' + encodeURIComponent(values[0][1]);
  };
  let match = vendor.exec(path);
  if (match) {
    const [,ticket,action,special] = match;
    if (method === 'GET' && (!ticket && !special || action === 'observations') && page()) return plan(CONNECTOR_HEADERS[0],0,65536);
    if (query) return null;
    if (method === 'GET' && (special === 'options' || ticket && !action)) return plan(CONNECTOR_HEADERS[0],0,65536);
    if (method === 'POST' && (!ticket && !special || special === 'resolve' || ticket && action && action !== 'observations'))
      return plan(CONNECTOR_HEADERS[0],!ticket && !special ? 32768 : action === 'result' ? 16384 : action === 'retire' ? 4096 : 2048,16384);
    return null;
  }
  match = artifact.exec(path);
  if (match) {
    if (query) return null;
    if (match[1] && method === 'PUT') return plan(CONNECTOR_HEADERS[0],8388608,8192,{seconds:60,binaryRequest:true});
    if (match[1] && method === 'GET') return plan(CONNECTOR_HEADERS[0],0,8388608,{seconds:60,binaryResponse:true});
    if (!match[1] && method === 'POST') return plan(CONNECTOR_HEADERS[0],2048,8192);
    return null;
  }
  match = finance.exec(path);
  if (match) {
    const [,ticket,action,special] = match;
    if (method === 'GET' && (!ticket && !special || action === 'observations') && page()) return plan(CONNECTOR_HEADERS[1],0,65536);
    if (query) return null;
    if (method === 'GET' && (special === 'options' || ticket && !action)) return plan(CONNECTOR_HEADERS[1],0,65536);
    if (method === 'POST' && (!ticket && !special || special === 'resolve' || ticket && action && action !== 'observations'))
      return plan(CONNECTOR_HEADERS[1],!ticket && !special || action === 'result' ? 16384 : 2048,16384);
    return null;
  }
  match = portalWork.exec(path);
  if (match) {
    if (query) return null;
    const [,ticket,action,special] = match;
    if (method === 'GET' && (!ticket && !special || ticket && (!action || action === 'observations')))
      return plan(CONNECTOR_HEADERS[3],0,2097152,{seconds:45});
    if (method === 'POST' && (!ticket && !special || special === 'resolve' || ticket && action && action !== 'observations'))
      return plan(CONNECTOR_HEADERS[3],16384,16384,{seconds:45});
    return null;
  }
  match = financeSetup.exec(path);
  if (match) {
    if (query) return null;
    const [,setup,history,command] = match;
    if (method === 'GET' && !command)
      return plan(CONNECTOR_HEADERS[4],0,!setup || history ? 131072 : 32768,{seconds:15});
    if (method === 'POST' && command)
      return plan(CONNECTOR_HEADERS[4],8192,8192,{seconds:15});
    return null;
  }
  match = vendorSetup.exec(path);
  if (match) {
    if (query) return null;
    const [,setup,history,command] = match;
    if (method === 'GET' && !command)
      return plan(CONNECTOR_HEADERS[6],0,!setup ? 131072 : history ? 1048576 : 32768,{seconds:15});
    if (method === 'POST' && command)
      return plan(CONNECTOR_HEADERS[6],8192,8192,{seconds:15});
    return null;
  }
  if (membershipSavedFinance.test(path))
    return method === 'GET' && !query ? plan(CONNECTOR_HEADERS[5],0,65536,{seconds:15}) : null;
  match = membership.exec(path);
  if (match) {
    if (query) return null;
    const [,ticket,action,special] = match;
    if (method === 'POST' && special === 'retire')
      return plan(CONNECTOR_HEADERS[5],16384,8192,{seconds:15});
    if (method === 'GET' && (!ticket && !special || special === 'options' || ticket && (!action || action === 'history')))
      return plan(CONNECTOR_HEADERS[5],0,special === 'options' ? 8192 : !ticket ? 131072 : action === 'history' ? 1048576 : 32768,{seconds:15});
    if (method === 'POST' && (!ticket && !special || special === 'resolve' || ticket && action && action !== 'history'))
      return plan(CONNECTOR_HEADERS[5],8192,8192,{seconds:15});
    return null;
  }
  match = portal.exec(path);
  if (match) {
    if (query) return null;
    if (method === 'GET' && !match[3]) return plan(CONNECTOR_HEADERS[2],0,2097152,{seconds:15});
    if (method === 'POST' && match[3]) return plan(CONNECTOR_HEADERS[2],8192,16384,{seconds:15});
    return null;
  }
  match = staff.exec(path);
  if (match && !query) {
    const [,ticket,action] = match;
    if (method === 'GET' && !action) return plan(CONNECTOR_HEADERS[0],0,!ticket || ticket.startsWith('pages/') ? 1048576 : 65536,{optional:true});
    if (method === 'POST' && ticket && !ticket.startsWith('pages/') && action)
      return plan(CONNECTOR_HEADERS[0],action === 'result' ? 16384 : 2048,16384,{optional:action === 'handoffs'});
  }
  return null;
}
