import { ENROLLMENT_CONTRACT, EnrollmentError, validateEnrollmentCheckout, validateEnrollmentConfig, validateEnrollmentDocument,
  validateEnrollmentInvitation, validateEnrollmentPractices, validateEnrollmentQuote, validateEnrollmentReceipt, validateEnrollmentStatus,
  type AgreementInput, type PracticeInput, type ProfileInput } from './enrollment-contract';

export type EnrollmentIdentity = { getToken: (options: { skipCache: true }) => Promise<string | null>; isCurrent: () => boolean };
async function verifiedDocument<T extends {html:string;sha256:string}>(value:T):Promise<T> {
  try{const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value.html));
    const actual=[...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
    if(actual!==value.sha256)throw new Error();return value;
  }catch{throw new EnrollmentError(502,'enrollment_document_changed');}
}
export function enrollmentApiBase(value = import.meta.env.VITE_ENROLLMENT_API_BASE, page = window.location.href): string {
  try {
    const api = new URL(value ?? ''), location = new URL(page);
    const loopback = (u: URL) => u.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(u.hostname);
    if (api.username || api.password || api.search || api.hash || api.pathname !== '/' ||
        location.username || location.password || !(api.protocol === 'https:' && location.protocol === 'https:' ||
          import.meta.env.DEV && loopback(api) && loopback(location))) throw new Error();
    return api.origin;
  } catch { throw new EnrollmentError(503, 'enrollment_not_configured'); }
}

/** Dedicated browser enrollment transport; never reuses clinical Org/Box headers or its API base. */
async function request<T>(base: string, path: string, validate: (value: unknown) => T,
  identity?: EnrollmentIdentity, body?: object, key?: string, signal?: AbortSignal, method = body ? 'POST' : 'GET'): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const interrupted = new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new EnrollmentError(timedOut?504:503)),{once:true}));
  void interrupted.catch(()=>{});
  const wait=<R,>(promise:Promise<R>)=>Promise.race([promise,interrupted]);
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, {once: true}); if (signal?.aborted) abort();
  let response: Response | undefined;
  const current = () => { if (controller.signal.aborted) throw new EnrollmentError(timedOut ? 504 : 503);
    if (identity && !identity.isCurrent()) throw new EnrollmentError(401, 'enrollment_authentication_required'); };
  try {
    current(); const headers = new Headers({Accept:'application/json','X-Cosmas-Enrollment-Contract':ENROLLMENT_CONTRACT});
    if (identity) {
      const token = await wait(identity.getToken({skipCache:true})); current();
      if (!token || /[\r\n]/.test(token)) throw new EnrollmentError(401, 'enrollment_authentication_required');
      headers.set('Authorization', `Bearer ${token}`);
    }
    if (body) headers.set('Content-Type','application/json');
    if (key) { if (!/^[A-Za-z0-9_-]{1,128}$/.test(key)) throw new EnrollmentError(422); headers.set('Idempotency-Key',key); }
    const encoded = body ? JSON.stringify(body) : undefined;
    if (encoded && new TextEncoder().encode(encoded).length > 16384) throw new EnrollmentError(422);
    current();
    response = await wait(fetch(base + '/enrollment/v1' + path, {method, headers, body:encoded,
      signal:controller.signal, credentials:'omit', redirect:'error', cache:'no-store', referrerPolicy:'no-referrer'}));
    current();
    if (response.redirected || response.type === 'opaque' || response.url&&response.url!==base+'/enrollment/v1'+path ||
        response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json' ||
        !response.headers.get('cache-control')?.split(',').some(item => item.trim().toLowerCase() === 'no-store')) throw new EnrollmentError(502);
    const reader = response.body?.getReader(); if (!reader) throw new EnrollmentError(502);
    const chunks: Uint8Array[] = []; let size = 0;
    try { for (;;) { current(); const part = await wait(reader.read()); current(); if (part.done) break;
      size += part.value.byteLength; if (size > 600000) throw new EnrollmentError(502); chunks.push(part.value); } }
    finally { void reader.cancel().catch(() => {}); reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.byteLength; }
    let value: unknown; try { value = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)); } catch { throw new EnrollmentError(502); }
    current();
    if (!response.ok) {
      const detail = value && typeof value === 'object' && 'detail' in value ? (value as {detail:unknown}).detail : null;
      const code=detail&&typeof detail==='object'&&'code'in detail?detail.code:detail;
      throw new EnrollmentError(response.status, typeof code === 'string' && /^enrollment_[a-z_]{1,80}$/.test(code) ? code : 'enrollment_unavailable');
    }
    return validate(value);
  } catch (error) { if(response&&[401,403].includes(response.status)&&!(error instanceof EnrollmentError&&error.code==='enrollment_signer_required'))throw new EnrollmentError(response.status,'enrollment_access_denied');
    if (error instanceof EnrollmentError) throw error;
    throw new EnrollmentError(timedOut ? 504 : 503); }
  finally { clearTimeout(timer); signal?.removeEventListener('abort',abort); controller.abort(); }
}

export function createEnrollmentApi(base: string) {
  return {
    config: (signal?:AbortSignal) => request(base,'/config',validateEnrollmentConfig,undefined,undefined,undefined,signal),
    status: (id:EnrollmentIdentity,signal?:AbortSignal) => request(base,'/status',validateEnrollmentStatus,id,undefined,undefined,signal),
    practices: (id:EnrollmentIdentity,signal?:AbortSignal) => request(base,'/practices',validateEnrollmentPractices,id,undefined,undefined,signal),
    selectPractice: (id:EnrollmentIdentity,body:{expected_revision:number;practice_id:string},key:string,signal?:AbortSignal) => request(base,'/select-practice',validateEnrollmentStatus,id,body,key,signal),
    profile: (id:EnrollmentIdentity,body:ProfileInput,key:string,signal?:AbortSignal) => request(base,'/profile',validateEnrollmentStatus,id,body,key,signal,'PUT'),
    practice: (id:EnrollmentIdentity,body:PracticeInput,key:string,signal?:AbortSignal) => request(base,'/practice',validateEnrollmentStatus,id,body,key,signal,'PUT'),
    join: (id:EnrollmentIdentity,body:{expected_revision:number;token:string},key:string,signal?:AbortSignal) => request(base,'/join',validateEnrollmentStatus,id,body,key,signal),
    document: (id:EnrollmentIdentity,signal?:AbortSignal) => request(base,'/baa/current',validateEnrollmentDocument,id,undefined,undefined,signal).then(verifiedDocument),
    accept: (id:EnrollmentIdentity,body:AgreementInput,key:string,signal?:AbortSignal) => request(base,'/baa/accept',validateEnrollmentStatus,id,body,key,signal),
    receipt: (id:EnrollmentIdentity,signal?:AbortSignal) => request(base,'/baa/receipt',validateEnrollmentReceipt,id,undefined,undefined,signal).then(async value=>{
      await verifiedDocument(value.document);return value;
    }),
    quote: (id:EnrollmentIdentity,signal?:AbortSignal) => request(base,'/quote',validateEnrollmentQuote,id,undefined,undefined,signal),
    checkout: (id:EnrollmentIdentity,body:{expected_revision:number},key:string,signal?:AbortSignal) => request(base,'/checkout',validateEnrollmentCheckout,id,body,key,signal),
    recover: (id:EnrollmentIdentity,body:{expected_revision:number},key:string,signal?:AbortSignal) => request(base,'/recover',validateEnrollmentStatus,id,body,key,signal),
    confirmWorkspace: (id:EnrollmentIdentity,body:{expected_revision:number;workspace_token:string},key:string,signal?:AbortSignal) => request(base,'/workspace/confirm',validateEnrollmentStatus,id,body,key,signal),
    invitation: (id:EnrollmentIdentity,body:{expected_revision:number;email:string;role:'admin'|'staff';can_sign:boolean},key:string,signal?:AbortSignal) => request(base,'/invitations',validateEnrollmentInvitation,id,body,key,signal),
    portal: (id:EnrollmentIdentity,body:{expected_revision:number},key:string,signal?:AbortSignal) => request(base,'/portal',value => {
      if (!value || typeof value !== 'object' || !('url' in value) || typeof value.url !== 'string') throw new EnrollmentError(502);
      return {url:value.url};
    },id,body,key,signal),
  };
}
export type EnrollmentApi = ReturnType<typeof createEnrollmentApi>;
export function stripeDestination(value: string, portal = false): string {
  try { const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port || url.hash ||
        url.hostname !== (portal ? 'billing.stripe.com' : 'checkout.stripe.com')) throw new Error();
    return url.href;
  } catch { throw new EnrollmentError(502, 'enrollment_destination_invalid'); }
}
export function workspaceDestination(value: string, page = window.location.href, approved:readonly string[] = []): string {
  try { const url = new URL(value,page), own = new URL(page);
    if (url.username || url.password || url.hash || !(url.origin === own.origin || approved.includes(url.origin)) ||
        !(url.protocol === 'https:' || import.meta.env.DEV && url.protocol === 'http:' && url.origin === own.origin)) throw new Error();
    return url.href;
  } catch { throw new EnrollmentError(502, 'enrollment_destination_invalid'); }
}
