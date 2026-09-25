import {act, createElement} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it, vi} from "vitest";

const harness = vi.hoisted(() => ({providers:0, tokens:vi.fn(async()=>"invented.hosted.token")}));
vi.mock("@clerk/react",()=>({
  ClerkProvider:({children}:{children:unknown})=>{harness.providers++;return children;},
  useAuth:()=>({isLoaded:true,isSignedIn:true,orgId:"org_invented",userId:"user_invented",sessionId:"sess_invented",getToken:harness.tokens}),
  OrganizationSwitcher:()=>null,UserButton:()=>null,SignIn:()=>"Invited sign in",
}));
vi.mock("./EncounterWorkspace",()=>({EncounterWorkspace:()=>"Connected private workspace"}));
vi.mock("./NativeAuthenticatedWorkspace",()=>({NativeAuthenticatedWorkspace:()=>"Native iPhone sign in"}));
vi.mock("./DesktopAuthenticatedWorkspace",()=>({DesktopAuthenticatedWorkspace:()=>"Native desktop sign in"}));
import {RuntimeApp} from "./runtime";
import {workspaceApi} from "./workspace-api";

let root:Root, container:HTMLDivElement;
const api="https://api.example.invalid";
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});harness.providers=0;harness.tokens.mockClear();
  for(const [key,value] of Object.entries({VITE_COSMAS_ENV:"early_adopter_beta",VITE_WORKSPACE_ENABLED:"true",
    VITE_WORKSPACE_AUTHENTICATED_ENABLED:"true",VITE_WORKSPACE_HOSTED_ENABLED:"true",VITE_WORKSPACE_DATA_MODE:"synthetic",
    VITE_WORKSPACE_HOSTED_CLIENT:"web",VITE_WORKSPACE_WEB_ORIGIN:"https://workspace.example.invalid",
    VITE_WORKSPACE_HOSTED_API_ORIGIN:api,VITE_API_BASE:api}))vi.stubEnv(key,value);
  vi.stubGlobal("window",{location:{href:"https://workspace.example.invalid/"}});
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({contract_version:1,state:"connected",role:"member",request:null}),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}})));
  container=document.createElement("div");document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllEnvs();vi.unstubAllGlobals();});
async function render(){await act(async()=>root.render(createElement(RuntimeApp,{runtimeMode:"early_adopter_beta",
  authenticatedWorkspace:true,workspaceEnabled:true,clerkPublishableKey:"pk_test_offline",apiBase:import.meta.env.VITE_API_BASE})));}

it("opens the shared workspace after sign in and sends a fresh token only to the configured service",async()=>{
  await render();expect(vi.mocked(fetch).mock.calls[0][0]).toBe(api+"/practice-access");expect(container.textContent).toContain("Connected private workspace");expect(container.textContent).toContain("invented data only");
  const fetcher=vi.fn(async()=>new Response("[]",{headers:{"Content-Type":"application/json"}}));vi.stubGlobal("fetch",fetcher);
  await workspaceApi.catalog({mode:"clerk_jwt",getToken:harness.tokens});
  expect(fetcher.mock.calls).toHaveLength(1);
  const call=fetcher.mock.calls[0] as unknown as [string,RequestInit];
  expect(call[0]).toBe(api+"/workspaces");expect(new Headers(call[1].headers).get("Authorization")).toBe("Bearer invented.hosted.token");
  expect(harness.tokens).toHaveBeenCalledWith({skipCache:true});
  expect(call[1]).toMatchObject({credentials:"omit",redirect:"error",cache:"no-store"});
});
it("a mismatched hosted page cannot initialize login or acquire credentials",async()=>{
  vi.stubGlobal("window",{location:{href:"https://unrelated.example.invalid/"}});await render();
  expect(container.textContent).toContain("connection is not configured");expect(harness.providers).toBe(0);
  await expect(workspaceApi.catalog({mode:"clerk_jwt",getToken:harness.tokens})).rejects.toThrow();
  expect(harness.tokens).not.toHaveBeenCalled();
});
it.each(["apple","desktop"])("selects %s native sign in for its hosted client",async client=>{
  vi.stubEnv("VITE_WORKSPACE_HOSTED_CLIENT",client);vi.stubEnv("VITE_WORKSPACE_WEB_ORIGIN","");
  vi.stubEnv(client==="apple"?"VITE_WORKSPACE_NATIVE_AUTH_ENABLED":"VITE_WORKSPACE_DESKTOP_AUTH_ENABLED","true");
  vi.stubEnv("VITE_API_BASE",client==="desktop"?"app://cosmas/api":api);
  vi.stubGlobal("window",{location:{href:client==="desktop"?"app://cosmas/index.html":"capacitor://localhost/index.html"}});
  await render();expect(container.textContent).toContain(client==="desktop"?"Native desktop sign in":"Native iPhone sign in");
  expect(harness.providers).toBe(0);
});
