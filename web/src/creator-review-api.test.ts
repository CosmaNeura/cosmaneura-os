// @ts-expect-error Vitest supplies Node crypto; production uses browser types.
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import golden from "../../tests/fixtures/creator_review.json";
import { creatorReviewApi } from "./creator-review-api";
import { CreatorReviewError, creatorReviewFailure } from "../../clients/scribe-review/creator-review-api";
import {request as captureRequest} from "./capture-api";
import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {mountCreatorReview} from "../../clients/scribe-review/creator-review-panel";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it("opens a complete 10,000-segment review through both bounded response readers", async () => {
  vi.stubGlobal("crypto",webcrypto); vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8018");
  const workspace="00000000-0000-4000-8000-000000000002", view=structuredClone(golden.ready);
  const source=view.source.segments[0], working=view.working.segments[0];
  view.source.segments=[]; view.working.segments=[]; view.source.duration_ms=10_000_000;
  for (let i=0;i<10_000;i++) {
    const common={source_segment_id:crypto.randomUUID(),start_ms:i*1000,end_ms:(i+1)*1000,content:"🩺".repeat(50)};
    view.source.segments.push({...source,...common});
    view.working.segments.push({...working,...common});
  }
  const body=JSON.stringify({workspace_id:workspace,session_id:view.session_id,operation:"creator_review",receipt:view});
  expect(new TextEncoder().encode(body).length).toBeGreaterThan(8*1024*1024+4096);
  const fetcher=vi.fn().mockResolvedValue(new Response(body,{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}));
  vi.stubGlobal("fetch",fetcher);
  const api=creatorReviewApi(workspace,view.session_id,{mode:"clerk_jwt",getToken:async()=>"synthetic-token"});
  expect((await api.read()).source?.segments).toHaveLength(10_000);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

const workspace = "00000000-0000-4000-8000-000000000002";
function open(response: Response | Error) {
  vi.stubGlobal("crypto",webcrypto);vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8018");
  const fetcher=vi.fn();
  if(response instanceof Error)fetcher.mockRejectedValue(response);else fetcher.mockResolvedValue(response);
  vi.stubGlobal("fetch",fetcher);
  return {api:creatorReviewApi(workspace,golden.ready.session_id,{mode:"clerk_jwt",getToken:async()=>"synthetic-token"}),fetcher};
}
const jsonHeaders={"Content-Type":"application/json","Cache-Control":"no-store"};
async function failure(api:ReturnType<typeof creatorReviewApi>){
  try{await api.read();}catch(error){expect(error).toBeInstanceOf(CreatorReviewError);return error as CreatorReviewError;}
  throw Error("Expected a refused synthetic transcript read");
}

it.each([
  [403,"core_capture_access_unavailable","read","core_access_unavailable"],
  [409,"capture_connection_required","read","connection_required"],
  [409,"capture_saved_recording_changed","read","source_changed"],
  [503,"capture_request_unconfirmed","read","request_unavailable"],
  [503,"untrusted-private-body-marker","read","request_unavailable"],
]as const)("retains only closed phase metadata for HTTP %s / %s",async(status,detail,phase,reason)=>{
  const {api,fetcher}=open(Response.json({detail,private_detail:"untrusted-private-body-marker"},{status,headers:jsonHeaders}));
  const error=await failure(api);expect(error.failure).toEqual({phase,reason,status});
  expect(error.message).toBe("Creator transcript request failed.");expect(JSON.stringify(error)).not.toContain("untrusted-private-body-marker");
  expect(fetcher).toHaveBeenCalledOnce();
  expect(JSON.parse(fetcher.mock.calls[0][1].body).operation).toEqual({kind:"creator_review"});
});

it.each([
  ["capture_access_unavailable","authorization","access_unavailable","Your access to this workspace could not be confirmed. Check your session, then choose Refresh."],
  ["untrusted-private-body-marker","read","request_unavailable","The transcript could not be retrieved. Choose Refresh to check again."],
]as const)("classifies OS403 %s through the real capture request and existing review recovery message",async(detail,phase,reason,message)=>{
  const {api,fetcher}=open(Response.json({detail,private_detail:"untrusted-private-body-marker"},{status:403,headers:jsonHeaders}));
  const host=document.createElement("div");document.body.append(host);const dispose=mountCreatorReview(host,api);
  try{
    await vi.waitFor(()=>expect(host.textContent).toContain(message));
    expect(host.querySelector("code")?.textContent).toBe(`${phase}_response_403_${reason}`);
    expect(host.textContent).not.toContain("untrusted-private-body-marker");expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0][0]).toBe(`http://127.0.0.1:8018/workspaces/${workspace}/capture/operations`);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({session_id:golden.ready.session_id,operation:{kind:"creator_review"}});
  }finally{dispose();host.remove();}
});

it.each([
  ["malformed JSON",new TextEncoder().encode('{"private":"untrusted-private-body-marker"')],
  ["invalid UTF-8",new Uint8Array([0xc3,0x28])],
]as const)("classifies completed outer %s as an invalid response, not missing recording",async(_name,body)=>{
  const {api}=open(new Response(body,{headers:jsonHeaders}));
  const error=await failure(api);expect(error.kind).toBe("invalid_response");
  expect(error.failure).toEqual({phase:"response",reason:"invalid_response",status:null});
  expect(JSON.stringify(error)).not.toContain("untrusted-private-body-marker");
});

it.each([
  ["JSON",new TextEncoder().encode('{"private":"untrusted-private-body-marker"')],
  ["UTF-8",new Uint8Array([0xc3,0x28])],
]as const)("keeps malformed outer409 %s at shared unconfirmed503 so it cannot trigger capture conflict recovery",async(_format,body)=>{
  const {fetcher}=open(new Response(body,{status:409,headers:jsonHeaders}));
  try{await captureRequest(workspace,"operations",{mode:"clerk_jwt",getToken:async()=>"synthetic-token"},
    {session_id:golden.ready.session_id,idempotency_key:"synthetic-fixed-key",operation:{kind:"creator_review"}});}
  catch(error){expect(error).toBeInstanceOf(BffResponseError);expect(error).toMatchObject({status:503,code:"capture_receipt_invalid"});
    expect(fetcher).toHaveBeenCalledOnce();return;}
  throw Error("Expected malformed completed capture response to remain unconfirmed");
});

it("keeps a rejected transport unconfirmed without claiming response parsing failed",async()=>{
  const {api}=open(new Error("untrusted-private-transport-detail"));
  expect((await failure(api)).failure).toEqual({phase:"read",reason:"client_transport_unavailable",status:null});
});

it("refuses a successful response without no-store metadata before reading its transcript",async()=>{
  const {api}=open(Response.json({workspace_id:workspace,session_id:golden.ready.session_id,operation:"creator_review",receipt:golden.ready}));
  expect((await failure(api)).failure).toEqual({phase:"response",reason:"invalid_response",status:200});
});

it.each(["envelope","receipt"]as const)("classifies an altered %s without keeping its content",async(kind)=>{
  const view=structuredClone(golden.ready);if(kind==="receipt")view.working.source_transcript_version++;
  const {api}=open(Response.json({workspace_id:kind==="envelope"?golden.ready.session_id:workspace,
    session_id:view.session_id,operation:"creator_review",receipt:view},{headers:jsonHeaders}));
  expect((await failure(api)).failure).toEqual({phase:"response",reason:"invalid_response",status:null});
});

it("classifies unavailable credentials without making a transcript request",async()=>{
  const {fetcher}=open(new Error("Unexpected synthetic request"));
  const api=creatorReviewApi(workspace,golden.ready.session_id,{mode:"clerk_jwt",getToken:async()=>null});
  expect((await failure(api)).failure).toEqual({phase:"authorization",reason:"access_unavailable",status:401});
  expect(fetcher).not.toHaveBeenCalled();
});

it("strips unknown status/reason/phase and all arbitrary metadata",()=>{
  expect(creatorReviewFailure({phase:"untrusted-private-marker",reason:"untrusted-private-marker",status:418,
    body:"untrusted-private-marker",session_id:golden.ready.session_id},"recovery"))
    .toEqual({phase:"recovery",reason:"recovery_unavailable",status:null});
});
