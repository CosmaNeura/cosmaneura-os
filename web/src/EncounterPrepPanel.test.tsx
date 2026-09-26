import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {EncounterPrepPanel} from "./EncounterPrepPanel";
import {readEncounterPrep, type EncounterPrep} from "./encounter-prep-api";
vi.mock("./encounter-prep-api",()=>({readEncounterPrep:vi.fn()}));
const identity={mode:"clerk_jwt" as const,getToken:vi.fn()};
const bot={address:"visit_prep",team_revision:1};
const value:EncounterPrep={appointment_ref:"appointment_1",snapshot_sha256:"a".repeat(64),display_sha256:"d".repeat(64),additional_notes_available:true,
 sources:[{source_id:"visit_note_1",appointment_ref:"appointment_2",kind:"generated_visit_note",label:"SOAP · generated draft",source_at:"2026-09-18T10:00:00Z",content_sha256:"b".repeat(64),content:"Invented earlier plan",truncated:true,content_redacted:false}]};
let root:Root,container:HTMLDivElement;
async function mount(address="visit_prep",enabled=true){await act(async()=>root.render(<EncounterPrepPanel workspaceId="w" identity={identity} bot={{...bot,address}} name="Prep partner" enabled={enabled} locked={false}/>));}
async function click(){await act(async()=>container.querySelector("button")!.click());}
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();vi.mocked(readEncounterPrep).mockResolvedValue(value);container=document.createElement("div");document.body.append(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
it("requires a deliberate read and identifies draft status and excerpts",async()=>{
 await mount();expect(readEncounterPrep).not.toHaveBeenCalled();await click();
 expect(container.textContent).toContain("clinical review and signature have not been verified");
 expect(container.textContent).toContain("Invented earlier plan");expect(container.textContent).toContain("Showing an excerpt");
 expect(container.textContent).toContain("More saved records");
});
it("clears a previous source view when an access check fails",async()=>{
 await mount();await click();vi.mocked(readEncounterPrep).mockRejectedValue(new Error("private upstream sentinel"));await click();
 expect(container.textContent).not.toContain("Invented earlier plan");expect(container.textContent).not.toContain("private upstream sentinel");
 expect(container.textContent).toContain("could not be confirmed");
});
it("discards a late response after a different bot is selected",async()=>{
 let release!:(value:EncounterPrep)=>void;vi.mocked(readEncounterPrep).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
 await mount();await click();await mount("scribe");await act(async()=>release(value));
 expect(container.textContent).not.toContain("Invented earlier plan");
});
it("does not read when the bot or source is paused",async()=>{await mount("visit_prep",false);await click();expect(readEncounterPrep).not.toHaveBeenCalled();});

it.each([401,403,404])("invalidates the private workspace after an access-denied context read (%s)",async status=>{
 const denied=vi.fn();await act(async()=>root.render(<EncounterPrepPanel workspaceId="w" identity={identity} bot={bot} name="Prep" enabled locked={false} onAccessLost={denied}/>));
 await click();vi.mocked(readEncounterPrep).mockRejectedValue(new BffResponseError(status,"capture_unavailable",null));await click();
 expect(denied).toHaveBeenCalledOnce();expect(denied.mock.calls[0][0]).toMatchObject({status});expect(container.textContent).not.toContain("Invented earlier plan");
});
