import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ProviderTeamSettings } from "./ProviderTeamSettings";
import { supportsSkill, type BotRole, type ProviderTeam, type TeamConfiguration } from "./workspace-api";

const roles: BotRole[] = ["scribe", "visit_prep", "follow_up", "chief"];
const initial: ProviderTeam = { revision: 1, template_version: "provider-team-v3", llm: {enabled: false, model: "gpt-4.1"},
  configuration: {practice_context: "Invented practice", bots: roles.map(role => ({role, name: role, enabled: true,
    response_style: "brief", include_notebook: true, include_evidence: true}))},
  members: roles.map(role => ({role, name: role, agent_id: role, description: role, prompt: "Help", initials: role, capabilities: []})),
  custom_skills: [
    {key: "saved_context", label: "Saved context review", state: "local", connector: "Workspace", contract: null},
    {key: "work_status", label: "Work status and receipts", state: "local", connector: "F-8", contract: null},
    {key: "encounter_prep", label: "Saved intake and prior visit drafts", state: "awaiting_connection", connector: "Core", contract: null},
    {key: "calendar_availability", label: "Calendar availability", state: "enabled", connector: "Scheduling", contract: null},
  ]};

describe("custom bot creation", () => {
  let container: HTMLDivElement, root: Root, saved: TeamConfiguration | undefined;
  function Harness() {
    const [draft, setDraft] = useState(structuredClone(initial.configuration));
    const [selected, setSelected] = useState("scribe");
    return <ProviderTeamSettings team={initial} draft={draft} setDraft={setDraft} selected={selected}
      setSelected={setSelected} locked={false} onClose={() => {}} onSave={() => {saved = draft;}} />;
  }
  beforeEach(async () => {
    Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true}); saved = undefined;
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    await act(async () => root.render(<Harness />));
  });
  afterEach(async () => {await act(async () => root.unmount()); container.remove();});
  function button(label: string) {return [...container.querySelectorAll("button")].find(b => b.textContent === label)!;}
  function field(label: string) {return [...container.querySelectorAll("label")].find(l => l.textContent?.startsWith(label))!.querySelector("input,textarea") as HTMLInputElement;}
  async function fill(label: string, value: string) {
    const element = field(label);
    await act(async () => {
      Object.getOwnPropertyDescriptor(element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value")!.set!.call(element, value);
      element.dispatchEvent(new Event("input", {bubbles: true}));
    });
  }
  it("creates a distinct custom identity with a required job, instructions and chosen skills", async () => {
    await act(async () => button("Create custom bot").click());
    expect(button("Save team settings").disabled).toBe(true);
    await fill("Bot name", "Referral partner"); await fill("Job (required)", "Prepare referral checklists");
    await fill("Instructions", "List missing items first");
    await act(async () => {field("Calendar availability").click(); field("My saved notebook").click();});
    await act(async () => button("Save team settings").click());
    const bot = saved!.bots[4];
    expect(bot.role).toBe("custom"); expect(bot.instance_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(bot.job_focus).toBe("Prepare referral checklists"); expect(bot.working_preferences).toBe("List missing items first");
    expect(bot.skills).toEqual(["saved_context", "work_status", "calendar_availability"]);
    expect(bot.include_notebook).toBe(false); expect(supportsSkill(bot, "calendar_availability")).toBe(true);
    expect(supportsSkill(bot, "encounter_prep")).toBe(false);
    expect(saved!.bots.slice(0,4)).toEqual(initial.configuration.bots);
    expect(container.textContent).toContain("Prerequisite missing");
  });
  it("supports multiple independent custom bots and removes a skill without substituting a template", async () => {
    await act(async () => button("Create custom bot").click()); await fill("Job (required)", "First job");
    await act(async () => button("Create custom bot").click()); await fill("Job (required)", "Second job");
    await act(async () => field("Work status and receipts").click());
    await act(async () => button("Save team settings").click());
    expect(saved!.bots.slice(4).map(b => b.role)).toEqual(["custom", "custom"]);
    expect(new Set(saved!.bots.slice(4).map(b => b.instance_id)).size).toBe(2);
    expect(saved!.bots[5].skills).toEqual(["saved_context"]);
    expect(supportsSkill(saved!.bots[5], "work_status")).toBe(false);
  });
});
