// @ts-expect-error Vitest supplies Node crypto; production uses browser types.
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import golden from "../../tests/fixtures/creator_review.json";
import { creatorReviewApi } from "./creator-review-api";

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
