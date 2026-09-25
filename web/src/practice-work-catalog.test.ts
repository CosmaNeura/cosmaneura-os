// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { workspaceApi } from "./workspace-api";
import { validatePracticeWorkPage } from "./practice-work-catalog";
import { readVendorPracticeCatalog } from "./vendor-api";
import actual from "./__fixtures__/vendor-work/actual-shared-r2.json";

const item = actual.shared_accepted_detail;
const identity = {boxId:"00000000-0000-4000-8000-000000000099",actorId:item.viewer_id};
const page = () => ({items:[structuredClone(item)],people:[item.originator,item.responsible],next_cursor:null});
const response = (value: unknown) => new Response(JSON.stringify(value), {headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
afterEach(() => {vi.unstubAllGlobals();vi.unstubAllEnvs();});

it("negotiates and renders the actual full shared projection through the common catalog", async () => {
  vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8046");
  const fetch = vi.fn().mockResolvedValue(response(page()));vi.stubGlobal("fetch",fetch);
  expect(await workspaceApi.practiceWork(identity)).toEqual(page());
  expect(new Headers(fetch.mock.calls[0][1].headers).get("X-Cosmas-Vendor-Contract")).toBe("1");
  expect(fetch.mock.calls[0][0]).toBe("http://127.0.0.1:8046/practice-work");
});

it("rejects wrong viewer, duplicate work and leaked private keys before returning a catalog", async () => {
  await expect(validatePracticeWorkPage(page(), {...identity,actorId:identity.boxId})).rejects.toThrow();
  await expect(validatePracticeWorkPage({...page(),items:[item,item]}, identity)).rejects.toThrow();
  await expect(validatePracticeWorkPage({...page(),items:[{...item,private_reference:{vendor_id:"hidden"}}]}, identity)).rejects.toThrow();
  await expect(validatePracticeWorkPage({...page(),items:[{...item,work_kind:"unknown_vendor"}]}, identity)).rejects.toThrow();
});

it("refuses a vendor response through the legacy detail and completion surfaces", async () => {
  vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8046");
  vi.stubGlobal("fetch",vi.fn().mockImplementation(async()=>response(item)));
  await expect(workspaceApi.practiceWorkItem(identity,item.ticket_id)).rejects.toMatchObject({status:426});
  await expect(workspaceApi.completeWork(identity,item.ticket_id,{revision_id:item.revision_id,payload_hash:item.payload_hash,idempotency_key:"old-completion-key",evidence:"Invented"})).rejects.toMatchObject({status:426});
});

it("bounds the mixed catalog stream at 1 MiB without reducing existing 50-item pages", async () => {
  vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:8046");
  const maximum = '"' + "x".repeat(1048574) + '"';
  const fetch = vi.fn().mockResolvedValueOnce(new Response(maximum,{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}))
    .mockResolvedValueOnce(new Response(maximum+" ",{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}}));
  vi.stubGlobal("fetch",fetch);
  expect(await readVendorPracticeCatalog(identity,undefined,async v=>(v as string).length)).toBe(1048574);
  const verify = vi.fn(async()=>true);
  await expect(readVendorPracticeCatalog(identity,undefined,verify)).rejects.toMatchObject({status:503});
  expect(verify).not.toHaveBeenCalled();
});
