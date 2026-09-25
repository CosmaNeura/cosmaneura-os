import { useRef } from "react";
import { botAddress, type BotAddress, type BotRole, type ProviderTeam, type TeamConfiguration } from "./workspace-api";
import { BLOCKED_CAPABILITIES, type BlockedCapability } from "./team-setup-request";
import { BotAvatar } from "./BotAvatar";

export type ProviderTeamSettingsView = "full" | "overview" | "edit" | "advanced" | "practice" | "add" | "hidden";
export function ProviderTeamSettings({ team, draft, setDraft, selected, setSelected, locked, onSave, onClose, reviewRequired = false, setupAvailable = false, view = "full", onBotAdded }: {
  reviewRequired?: boolean; setupAvailable?: boolean; view?: ProviderTeamSettingsView; onBotAdded?: () => void;
  team: ProviderTeam; draft: TeamConfiguration; setDraft: (draft: TeamConfiguration) => void;
  selected: BotAddress; setSelected: (address: BotAddress) => void; locked: boolean; onSave: () => void; onClose: () => void;
}) {
  const beforeRetirement = useRef(new Map<BotAddress, {enabled:boolean;retired?:boolean}>());
  const bot = draft.bots.find(b => botAddress(b) === selected) ?? draft.bots[0];
  const templates = team.templates ?? team.members.filter(b => !b.instance_id && b.role !== "chief" && b.role !== "custom");
  const template = bot.role === "custom" ? {name: "Custom bot", description: "Give this coworker a job, instructions and the skills it needs.", capabilities: []}
    : team.members.find(b => botAddress(b) === botAddress(bot)) ?? templates.find(b => b.role === bot.role)!;
  const savedBot = team.configuration.bots.find(b => botAddress(b) === botAddress(bot));
  const currentCount = draft.bots.filter(b => !b.retired).length;
  const cannotAdd = locked || currentCount >= 12 || draft.bots.length >= 100;
  const fieldsLocked = locked || !!bot.retired;
  const blockedLabels: Record<BlockedCapability,string> = {model_answer:"Block AI answers",private_draft_handoff:"Block private bot assignments",practice_work_brief:"Block scheduled work briefs"};
  const status = (key:string, state:string) => bot.retired ? "Retired" : !bot.enabled ? "Paused" :
    (key === "assistant.answer" && bot.blocked_capabilities?.includes("model_answer") || key === "workspace.draft.handoff" &&
      bot.blocked_capabilities?.some(cap => cap === "model_answer" || cap === "private_draft_handoff")) ? "Blocked by your settings" :
      (key === "assistant.answer" || key === "workspace.draft.handoff") && draft.model_work?.max_attempts_per_24h === 0 ? "New model work paused by team policy" :
      (key === "encounter_prep" || key === "calendar_availability") && bot.resources && !bot.resources.allowed.some(b=>b.purpose===(key==='encounter_prep'?'core_preparation':'scheduling_context')) ? "Source purpose restricted" :
      state === "local" ? "Local tool" : state === "enabled" ? "Runtime available · scope required" : "Prerequisite missing";
  function change(update: Partial<typeof bot>) {
    setDraft({ ...draft, bots: draft.bots.map(b => botAddress(b) === botAddress(bot) ? { ...b, ...update } : b) });
  }
  function toggleRetirement() {
    if (locked || !savedBot || savedBot.retired) return;
    const address = botAddress(bot);
    if (bot.retired) {
      const previous=beforeRetirement.current.get(address),restored={...bot,enabled:previous?.enabled??savedBot.enabled};
      if(previous?.retired===undefined)delete restored.retired;else restored.retired=previous.retired;
      setDraft({...draft,bots:draft.bots.map(item=>botAddress(item)===address?restored:item)});
      beforeRetirement.current.delete(address);
    } else {
      beforeRetirement.current.set(address, {enabled:bot.enabled,...(bot.retired===undefined?{}:{retired:bot.retired})});
      change({retired: true, enabled: false});
    }
  }
  function add(role: BotRole) {
    if (cannotAdd) return;
    const chosen = templates.find(t => t.role === role);
    if (!chosen || role === "chief") return;
    const instance_id = crypto.randomUUID();
    const number = draft.bots.filter(b => b.role === role).length + 1;
    setDraft({ ...draft, bots: [...draft.bots, { role, instance_id, name: `${chosen.name} ${number}`,
      enabled: true, response_style: "brief", include_notebook: role !== "research", include_evidence: role !== "research",
      job_focus: "", working_preferences: "" }] });
    setSelected(instance_id);onBotAdded?.();
  }
  function addCustom() {
    if (cannotAdd || !team.custom_skills) return;
    const instance_id = crypto.randomUUID();
    setDraft({...draft, bots: [...draft.bots, {role: "custom", instance_id, name: "My custom bot",
      enabled: true, response_style: "brief", include_notebook: true, include_evidence: true,
      job_focus: "", working_preferences: "", skills: ["saved_context", "work_status"]}]});
    setSelected(instance_id);onBotAdded?.();
  }
  if(view === "hidden")return null;
  if(view === "overview")return <section className="team-coworker-overview" aria-label="Your coworkers">
    <ul>{draft.bots.filter(member=>!member.retired).map(member=><li key={botAddress(member)}><button onClick={()=>setSelected(botAddress(member))}>
      <BotAvatar role={member.role}/><span><strong>{member.name||"Name this coworker"}</strong><small>{member.role==='custom'?(member.job_focus||'Give this coworker a job'):member.job_focus||'Private encounter help'}</small></span>
      <span className="team-flow-state">{member.enabled?'On':'Paused'}</span><span aria-hidden="true">›</span></button></li>)}</ul>
    {draft.bots.some(member=>member.retired)&&<details><summary>Retired coworkers · history kept</summary>{draft.bots.filter(member=>member.retired).map(member=><button key={botAddress(member)} onClick={()=>setSelected(botAddress(member))}>{member.name} · Retired</button>)}</details>}
  </section>;
  if(view === "add")return <section className="team-add-coworker" aria-label="Add a coworker">
    <button className="team-primary" disabled={cannotAdd||!team.custom_skills} onClick={addCustom}>Create custom bot</button>
    <p>Or start from an existing role. You can change its name and job.</p>
    <div className="team-template-choices">{templates.map(t=><button key={t.role} disabled={cannotAdd} onClick={()=>add(t.role)}><strong>{t.name}</strong><span>{t.description}</span></button>)}</div>
    {cannotAdd&&!locked&&<p role="status">The current team or retained history limit is reached. Existing coworkers and their work remain available.</p>}
  </section>;
  if(view === "practice")return <section className="team-practice-editor"><label>Practice context<textarea rows={5} maxLength={1000} value={draft.practice_context} disabled={locked}
    onChange={e=>setDraft({...draft,practice_context:e.target.value})}/></label><p>This preference applies to the whole team. It does not grant permission to act.</p></section>;
  const full=view==='full',essential=full||view==='edit',advanced=full||view==='advanced';
  return <section className={`team-settings${full?'':' team-settings-focused'}`} aria-label="Provider Team settings">
    {full&&<div className="team-section-heading"><div><p className="team-kicker">YOUR COWORKERS</p><h2>{team.revision ? "Make the team yours" : "Set up your Provider Team"}</h2>
      <p>Choose coworkers for your practice, give each a focus, and control the saved context they can use.</p></div>
      <button className="team-icon-button" onClick={onClose} aria-label="Close team settings">×</button></div>}
    <div className="team-settings-grid">{full&&<nav aria-label="Choose a bot to configure" className="team-settings-roster">
      {draft.bots.map(member => <button key={botAddress(member)} onClick={() => setSelected(botAddress(member))} aria-pressed={botAddress(bot) === botAddress(member)}>
        <BotAvatar role={member.role} />
        <span><strong>{member.name || team.members.find(t => t.role === member.role)?.name}</strong><small>{member.retired ? team.configuration.bots.find(b => botAddress(b) === botAddress(member))?.retired ? "Retired · history kept" : "Retire on save" : !team.configuration.bots.some(b => botAddress(b) === botAddress(member)) ? "Save to add to your team" : member.enabled ? "Included in your team" : "Paused"}</small></span>
      </button>)}
      <label>Add a bot<select aria-label="Add a bot" value="" disabled={cannotAdd}
        onChange={event => add(event.target.value as BotRole)}>
        <option value="">Choose a template…</option>{templates.map(t => <option key={t.role} value={t.role}>{t.name}</option>)}
      </select></label>
      <button type="button" disabled={cannotAdd || !team.custom_skills} onClick={addCustom}>Create custom bot</button>
      {currentCount >= 12 && <p className="team-fine">Your team has 12 current bots. Retire an added bot to make room for another.</p>}
      {draft.bots.length >= 100 && <p className="team-fine">This team's saved bot history is full. Existing bots and their history remain available.</p>}
    </nav>}<div className="team-settings-detail">
      {full&&<div className="team-bot-intro"><BotAvatar role={bot.role} large />
        <div><h3>{template.name}</h3><p>{template.description}</p></div></div>}
      <div className="team-settings-form">
        {essential&&<><label>Bot name<input maxLength={40} value={bot.name} disabled={fieldsLocked} onChange={e => change({ name: e.target.value })} /></label>
        <label>{bot.role === "custom" ? "Job (required)" : "Job focus"}<input maxLength={500} value={bot.job_focus ?? ""} disabled={fieldsLocked} required={bot.role === "custom"}
          placeholder={bot.role === "custom" ? "For example, prepare referral checklists" : "For example, visit documentation"} onChange={e => change({ job_focus: e.target.value })} /></label>
        <label>{bot.role === "custom" ? "Instructions" : "Working preferences"}<textarea rows={3} maxLength={2000} value={bot.working_preferences ?? ""} disabled={fieldsLocked}
          placeholder="How would you like this bot to help?" onChange={e => change({ working_preferences: e.target.value })} /></label></>}
        {advanced&&<><label className="team-check"><input type="checkbox" checked={bot.enabled} disabled={fieldsLocked} onChange={e => change({ enabled: e.target.checked })} />Enable this bot</label>
        <label>Review length<select value={bot.response_style} disabled={fieldsLocked} onChange={e => change({ response_style: e.target.value as "brief" | "detailed" })}>
          <option value="brief">Brief</option><option value="detailed">More detail</option>
        </select></label>
        <fieldset disabled={fieldsLocked}><legend>Sources this bot can use in your encounter</legend>
          <label className="team-check"><input type="checkbox" checked={bot.include_notebook} onChange={e => change({ include_notebook: e.target.checked })} />My saved notebook</label>
          <label className="team-check"><input type="checkbox" checked={bot.include_evidence} onChange={e => change({ include_evidence: e.target.checked })} />Saved preparation and evidence</label>
        </fieldset>
        <fieldset disabled={fieldsLocked || !setupAvailable}><legend>Capability restrictions</legend>
          {BLOCKED_CAPABILITIES.map(capability => <label className="team-check" key={capability}><input type="checkbox"
            checked={bot.blocked_capabilities?.includes(capability) ?? false} onChange={e => change({blocked_capabilities:e.target.checked
              ? [...(bot.blocked_capabilities ?? []), capability] : (bot.blocked_capabilities ?? []).filter(value => value !== capability)})}/>{blockedLabels[capability]}</label>)}
        </fieldset>
        {!setupAvailable && <p className="team-fine">Capability changes require the current team setup prerequisites to be available.</p>}
        <p className="team-fine">Responsible human: you. These settings do not grant external action authority. Your conversations remain private.</p>
        {bot.instance_id && savedBot && <div className="team-retirement">
          <p className="team-fine">{savedBot.retired ? "This bot is retired. Its conversations and assignments remain available, and it cannot take new work." : bot.retired ? "Saving will permanently retire this bot. Its history stays available. A replacement will have its own history." : "Retiring this bot preserves its history and stops new work. Pause it instead if you may want to use it again."}</p>
          {!savedBot.retired && <button type="button" disabled={locked} onClick={toggleRetirement}>{bot.retired ? "Undo retirement" : "Retire bot when saved"}</button>}
        </div>}</>}
      </div>
      {advanced&&<><h4>Skills & connections</h4>
      {bot.role === "custom" && <fieldset disabled={fieldsLocked} className="team-custom-skills"><legend>Choose this bot's skills</legend>
        {(team.custom_skills ?? []).map(skill => <label className="team-check" key={skill.key}>
          <input type="checkbox" checked={(bot.skills ?? []).includes(skill.key)} onChange={e => change({skills: e.target.checked
            ? [...(bot.skills ?? []), skill.key] : (bot.skills ?? []).filter(key => key !== skill.key)})} />
          <span>{skill.label}<small className="team-fine">{status(skill.key,skill.state)}</small></span>
        </label>)}
        <p className="team-fine">Private bot assignments require permitted saved sources, work status and current capability checks. Each prep or calendar read checks its current scope and account mapping.</p>
      </fieldset>}
      <ul className="team-capability-list">{template.capabilities.map(capability => <li key={capability.key}>
        <span><strong>{capability.label}</strong><small>{capability.connector}</small></span>
        <span className={`team-pill ${capability.state === "awaiting_connection" ? "pending" : "available"}`}>{status(capability.key,capability.state)}</span>
      </li>)}</ul></>}
      {full&&<><label className="team-practice">Practice context<textarea rows={2} maxLength={1000} value={draft.practice_context} disabled={locked}
        onChange={e => setDraft({ ...draft, practice_context: e.target.value })} /></label>
      <p className="team-fine">{team.llm.enabled && !bot.blocked_capabilities?.includes("model_answer") ? "Used as preferences for permitted GPT-4.1 requests. These cannot grant permission to act." : "Saved for connected skills. Local source lookup does not interpret practice instructions."}</p></>}
    </div></div>
    {full&&reviewRequired && <p className="team-fine" role="status">Run the invented rehearsal and review this draft before saving preset, capability, attempt-limit or source-policy changes.</p>}
    {full&&<footer className="team-settings-footer"><span>{team.revision ? `Saved configuration · revision ${team.revision}` : "Ready to personalize"}</span>
      <button className="team-primary" disabled={locked || reviewRequired || draft.bots.some(b => !b.name.trim() || b.role === "custom" && !b.job_focus?.trim())} onClick={onSave}>{team.revision ? "Save team settings" : "Set up Provider Team"}</button></footer>}
  </section>;
}
