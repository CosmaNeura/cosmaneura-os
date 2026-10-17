from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from cosmas_os.api.session_prep_analysis_schemas import ConversationAnalysisFields
from cosmas_os.api.workspace_schemas import IdempotencyKey

BotRole = Literal["scribe", "visit_prep", "follow_up", "chief", "custom", "research"]
BotSkill = Literal["saved_context", "work_status", "encounter_prep", "calendar_availability", "inbox_review", "membership_review"]
BlockedCapability = Literal["model_answer", "private_draft_handoff", "practice_work_brief"]
PresetId = Literal["provider", "front_desk", "practice_manager"]
BotAddress = Annotated[str, Field(pattern=r"^(?:scribe|visit_prep|follow_up|chief|[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")]
PRESET_SLOTS = {
    "provider": ("scribe", "visit_prep", "follow_up", "chief"),
    "front_desk": ("inbox", "scheduling", "intake"),
    "practice_manager": ("operations", "membership_billing", "chief"),
}


class PresetBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset_id: PresetId
    version: int = Field(ge=1, le=2, strict=True)
    slots: dict[str, BotAddress]

    @model_validator(mode="after")
    def exact_slots(self):
        if self.version == 2 and self.preset_id not in {"front_desk", "practice_manager"}:
            raise ValueError("invalid preset version")
        if type(self.version) is not int or set(self.slots) != set(PRESET_SLOTS[self.preset_id]):
            raise ValueError("invalid preset inventory")
        for slot, address in self.slots.items():
            if self.preset_id == "provider" or slot == "chief":
                if address != slot:
                    raise ValueError("baseline identity cannot change")
            elif address in {"scribe", "visit_prep", "follow_up", "chief"}:
                raise ValueError("custom slot requires its own identity")
        return self


class ModelWorkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, le=1, strict=True)
    max_attempts_per_24h: int = Field(ge=0, le=1000, strict=True)


class ResourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["core_preparation", "scheduling_context"]
    resource_ref: str = Field(pattern=r"^[0-9a-f]{64}$")


class BotResources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, le=1, strict=True)
    allowed: list[ResourceBinding] = Field(max_length=2)

    @model_validator(mode="after")
    def distinct_purposes(self):
        if len({value.purpose for value in self.allowed}) != len(self.allowed):
            raise ValueError("distinct resource purposes required")
        return self


class BotSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: BotRole
    name: str = Field(min_length=1, max_length=40)
    enabled: bool = Field(strict=True)
    response_style: Literal["brief", "detailed"] = "brief"
    include_notebook: bool = Field(default=True, strict=True)
    include_evidence: bool = Field(default=True, strict=True)
    instance_id: UUID4 | None = None
    job_focus: str = Field(default="", max_length=500)
    working_preferences: str = Field(default="", max_length=2000)
    retired: bool = Field(default=False, strict=True)
    skills: list[BotSkill] = Field(default_factory=list, max_length=6)
    blocked_capabilities: list[BlockedCapability] = Field(default_factory=list, max_length=3)
    resources: BotResources | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_resources_not_null(cls, value):
        if isinstance(value, dict) and "resources" in value and value["resources"] is None:
            raise ValueError("resource policy must be absent or explicit")
        return value

    @model_serializer(mode="wrap")
    def preserve_absent_resources(self, handler):
        value = handler(self)
        if self.resources is None:
            value.pop("resources", None)
        return value

    @model_validator(mode="after")
    def retirement_is_inactive_instance(self):
        if self.role == "research" and self.instance_id is None:
            raise ValueError("Research uses its own private instance identity")
        if self.role == "custom" and (self.instance_id is None or not self.job_focus):
            raise ValueError("a custom bot requires its own identity and a job focus")
        if len(set(self.skills)) != len(self.skills) or self.role != "custom" and self.skills:
            raise ValueError("select distinct supported skills for custom bots only")
        if len(set(self.blocked_capabilities)) != len(self.blocked_capabilities):
            raise ValueError("select distinct restrictions")
        if any(0xD800 <= ord(character) <= 0xDFFF for value in
               (self.name, self.job_focus, self.working_preferences) for character in value):
            raise ValueError("invalid unicode")
        if self.retired and (self.enabled or self.instance_id is None):
            raise ValueError("only an additional, disabled bot can be retired")
        return self


class PracticeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: Literal[1]
    practice_name: str = Field(default="", max_length=100)
    specialty: str = Field(default="", max_length=80)
    provider_name: str = Field(default="", max_length=80)
    credentials: str = Field(default="", max_length=40)
    state: str = Field(default="", max_length=40)
    note_format: str = Field(default="", max_length=60)
    language: str = Field(default="", max_length=40)

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("practice profile version required")
        return value

    @model_validator(mode="after")
    def unicode_scalars(self):
        if any(0xD800 <= ord(char) <= 0xDFFF or ord(char) < 32 for key, value in self.model_dump().items()
               if key != "version" for char in value):
            raise ValueError("invalid practice profile text")
        return self


class TeamConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    practice_context: str = Field(default="Direct Primary Care", max_length=1000)
    bots: list[BotSettings] = Field(min_length=4, max_length=100)
    presets: list[PresetBinding] = Field(default_factory=list, max_length=3)
    model_work: ModelWorkPolicy | None = None
    practice_profile: PracticeProfile | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_work_policy_not_null(cls, value):
        if isinstance(value, dict) and any(key in value and value[key] is None for key in ("model_work", "practice_profile")):
            raise ValueError("work policy must be absent or explicit")
        return value

    @model_serializer(mode="wrap")
    def preserve_absent_policy(self, handler):
        value = handler(self)
        if self.model_work is None:
            value.pop("model_work", None)
        if self.practice_profile is None:
            value.pop("practice_profile", None)
        return value

    @model_validator(mode="after")
    def all_roles_once(self):
        from cosmas_os.application.practice_profile import context
        if len(context({"practice_profile": self.practice_profile.model_dump() if self.practice_profile else None,
                        "practice_context": self.practice_context})) > 1000:
            raise ValueError("practice profile and additional instructions exceed the helper context limit")
        if sum(not bot.retired for bot in self.bots) > 12:
            raise ValueError("a Provider Team can contain at most twelve current bots")
        baseline = [bot for bot in self.bots if bot.instance_id is None]
        if len(baseline) != 4 or {bot.role for bot in baseline} != {"scribe", "visit_prep", "follow_up", "chief"}:
            raise ValueError("each baseline Provider Team role is required exactly once")
        extra = [bot for bot in self.bots if bot.instance_id is not None]
        if len({bot.instance_id for bot in extra}) != len(extra) or any(bot.role == "chief" for bot in extra):
            raise ValueError("additional bots require distinct identities and cannot be Chief")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in self.practice_context):
            raise ValueError("invalid unicode")
        if len({preset.preset_id for preset in self.presets}) != len(self.presets):
            raise ValueError("distinct presets required")
        if self.presets and not any(p.preset_id == "provider" for p in self.presets):
            raise ValueError("provider binding required")
        roster = {str(bot.instance_id) if bot.instance_id else bot.role: bot for bot in self.bots}
        seen = set()
        for preset in self.presets:
            for slot, address in preset.slots.items():
                if address not in roster or (address in seen and address != "chief"):
                    raise ValueError("invalid private slot identity")
                if preset.preset_id != "provider" and slot != "chief" and roster[address].role != "custom":
                    raise ValueError("custom slot requires a custom bot")
                seen.add(address)
        return self


class SetupReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_version: int = Field(ge=1, le=5, strict=True)
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prerequisites_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def strict_version(self):
        if type(self.catalog_version) is not int:
            raise ValueError("invalid catalog version")
        return self


class TeamRehearsalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    configuration: TeamConfiguration
    scenario_id: Literal["preset_setup.v1", "team_policy_setup.v1"]


class TeamSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    idempotency_key: IdempotencyKey
    configuration: TeamConfiguration
    setup_review: SetupReview | None = None


class ConversationRequest(ConversationAnalysisFields):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1, strict=True)
    team_revision: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    role: BotAddress
    content: str = Field(min_length=1, max_length=4000)


class HandoffRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    previous_attempt_id: UUID
    idempotency_key: IdempotencyKey
