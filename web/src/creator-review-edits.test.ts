// @ts-expect-error Test-only Node crypto; production uses browser types.
import {webcrypto} from "node:crypto";
import {afterEach,expect,it,vi} from "vitest";
import edited from "../../tests/fixtures/creator_review_edited.json";
import {parseCreatorReview} from "../../clients/scribe-review/creator-review-api";
import {mountCreatorReview} from "../../clients/scribe-review/creator-review-panel";
import {creatorReviewApi} from "./creator-review-api";
import {parseExistingScribeSource} from "./scribe-source-api";

afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});
const workspace="00000000-0000-4000-8000-000000000099";

it("reads and shows current Core's corrected English words and role, retaining the original",async()=>{
  vi.stubGlobal("crypto",webcrypto);vi.stubEnv("VITE_API_BASE","http://127.0.0.1:8018");
  const value=structuredClone(edited),before=JSON.stringify(value);
  const fetcher=vi.fn().mockResolvedValue(Response.json({workspace_id:workspace,session_id:value.session_id,
    operation:"creator_review",receipt:value},{headers:{"Cache-Control":"no-store"}}));
  vi.stubGlobal("fetch",fetcher);
  const api=creatorReviewApi(workspace,value.session_id,{mode:"clerk_jwt",getToken:async()=>"synthetic-token"});
  const host=document.createElement("div");document.body.append(host);
  const dispose=mountCreatorReview(host,api);
  try{
    await vi.waitFor(()=>expect(host.textContent).toContain("English · current text"));
    const segment=host.querySelector(".creator-segment")!;
    expect(segment.querySelector(".creator-segment-heading strong")?.textContent).toBe("Provider");
    expect(segment.querySelector(".creator-language-grid > div > p")?.textContent).toBe("Synthetic mild wrist soreness.");
    const original=segment.querySelector("details")!;
    expect(original.querySelector("summary")?.textContent).toBe("Original English words");
    expect(original.querySelector("p")?.textContent).toBe("Synthetic wrist soreness.");
    expect(segment.textContent).toContain("Original speaker: Patient");
    original.open=true;expect(original.open).toBe(true);
    expect(host.querySelector('[data-review-action="accepted"]')).toBeNull();
    expect(fetcher).toHaveBeenCalledOnce();
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({session_id:value.session_id,operation:{kind:"creator_review"}});
    expect(JSON.stringify(value)).toBe(before);
  }finally{dispose();host.remove();}
});

it.each(["wrong_text","wrong_role","foreign_working","foreign_source","foreign_segment","foreign_speaker",
  "future_version","segment_version","duplicate_edit","unknown_field","naive_timestamp","overlong_text","missing_both_fields"])(
  "withholds an edited view with %s instead of displaying or adopting its projection",async fault=>{
    const value=structuredClone(edited),edit=value.review_edits[0];
    if(fault==="wrong_text")value.working.segments[0].content="Unevidenced synthetic assertion";
    if(fault==="wrong_role")value.working.segments[0].speaker_role="other";
    if(fault==="foreign_working")edit.request.expected_working_transcript_id=workspace;
    if(fault==="foreign_source")edit.request.expected_source_transcript_version=2;
    if(fault==="foreign_segment")edit.request.corrections[0].source_segment_id=workspace;
    if(fault==="foreign_speaker")edit.request.speakers[0].speaker_id=workspace;
    if(fault==="future_version"){edit.working_transcript_version=3;edit.request.expected_working_transcript_version=2;}
    if(fault==="segment_version")edit.request.corrections[0].expected_source_segment_version=2;
    if(fault==="duplicate_edit")value.review_edits.push(structuredClone(edit));
    if(fault==="unknown_field")Object.assign(edit.request,{untrusted_permission:true});
    if(fault==="naive_timestamp")edit.created_at="2026-10-21T00:00:00";
    if(fault==="overlong_text")edit.request.corrections[0].content="x".repeat(100001);
    if(fault==="missing_both_fields"){
      Reflect.deleteProperty(value,"review_edits");Reflect.deleteProperty(value,"editing_allowed");
    }
    expect(()=>parseCreatorReview(value,value.session_id)).toThrow();
    await expect(parseExistingScribeSource({contract_version:1,workspace_id:workspace,status:"available",review:value,
      selection:{version:1,session_id:value.session_id,source_transcript_version:1,working_transcript_id:value.working.working_transcript_id,
        working_transcript_version:2,snapshot_sha256:"a".repeat(64)}},workspace)).rejects.toMatchObject({code:"scribe_source_receipt_invalid"});
  });

it("keeps the same edited source and exact working version through the saved-note destination",async()=>{
  const view=structuredClone(edited),selection={version:1,session_id:view.session_id,source_transcript_version:1,
    working_transcript_id:view.working.working_transcript_id,working_transcript_version:2,snapshot_sha256:"a".repeat(64)};
  const result=await parseExistingScribeSource({contract_version:1,workspace_id:workspace,status:"available",review:view,selection},workspace);
  expect(result.review?.source?.segments[0].content).toBe("Synthetic wrist soreness.");
  expect(result.review?.working?.segments[0].content).toBe("Synthetic mild wrist soreness.");
  expect(result.review?.review_edits).toEqual(view.review_edits);expect(result.selection).toEqual(selection);
});
