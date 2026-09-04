def env($name):
  first(.properties.template.containers[0].env[] | select(.name == $name));
def absent_or_null($object; $key):
  ($object | has($key) | not) or $object[$key] == null;
def absent_or_empty_array($object; $key):
  ($object | has($key) | not) or
  (($object[$key] | type) == "array" and ($object[$key] | length) == 0);

(.id | ascii_downcase) == $job_id and
(.properties.environmentId | ascii_downcase) == $environment_id and
.identity.type == "UserAssigned" and
((.identity.userAssignedIdentities | keys | map(ascii_downcase)) == [$identity_id]) and
.properties.configuration.triggerType == "Manual" and
.properties.configuration.replicaTimeout == 900 and
.properties.configuration.replicaRetryLimit == 0 and
((.properties.configuration | keys) - [
  "eventTriggerConfig",
  "identitySettings",
  "manualTriggerConfig",
  "registries",
  "replicaRetryLimit",
  "replicaTimeout",
  "scheduleTriggerConfig",
  "secrets",
  "triggerType"
] | length) == 0 and
absent_or_null(.properties.configuration; "eventTriggerConfig") and
absent_or_null(.properties.configuration; "scheduleTriggerConfig") and
absent_or_null(.properties.configuration; "identitySettings") and
((.properties.configuration.manualTriggerConfig | keys) - [
  "parallelism",
  "replicaCompletionCount"
] | length) == 0 and
.properties.configuration.manualTriggerConfig.parallelism == 1 and
.properties.configuration.manualTriggerConfig.replicaCompletionCount == 1 and
(.properties.configuration.registries | type) == "array" and
(.properties.configuration.registries | length) == 1 and
(.properties.configuration.registries[0] | keys) == ["identity", "server"] and
.properties.configuration.registries[0].server == $registry and
(.properties.configuration.registries[0].identity | ascii_downcase) == $identity_id and
(.properties.configuration.secrets | type) == "array" and
(.properties.configuration.secrets | length) == 4 and
all(.properties.configuration.secrets[]; keys == ["identity", "keyVaultUrl", "name"]) and
([.properties.configuration.secrets[] | {
  name,
  identity: (.identity | ascii_downcase),
  keyVaultUrl
}] | sort_by(.name)) == ([
  {name: "acceptance-hmac-key", identity: $identity_id, keyVaultUrl: $hmac_secret},
  {name: "database-url", identity: $identity_id, keyVaultUrl: $database_secret},
  {name: "human-deploy-evidence-reference", identity: $identity_id, keyVaultUrl: $evidence_secret},
  {name: "redis-url", identity: $identity_id, keyVaultUrl: $redis_secret}
] | sort_by(.name)) and
((.properties.template | keys) - ["containers", "initContainers", "volumes"] | length) == 0 and
absent_or_empty_array(.properties.template; "initContainers") and
absent_or_empty_array(.properties.template; "volumes") and
(.properties.template.containers | type) == "array" and
(.properties.template.containers | length) == 1 and
((.properties.template.containers[0] | keys) - [
  "args",
  "command",
  "env",
  "image",
  "name",
  "probes",
  "resources",
  "volumeMounts"
] | length) == 0 and
.properties.template.containers[0].name == "runtime-acceptance" and
.properties.template.containers[0].image == $image and
.properties.template.containers[0].command == ["python", "-m", "cosmas_os.cli"] and
.properties.template.containers[0].args == [
  "verify-beta-runtime",
  "--confirm-synthetic-only",
  "--confirm-runtime-uami"
] and
.properties.template.containers[0].resources.cpu == 0.25 and
.properties.template.containers[0].resources.memory == "0.5Gi" and
((.properties.template.containers[0].resources | keys) - [
  "cpu",
  "ephemeralStorage",
  "memory"
] | length) == 0 and
((.properties.template.containers[0].resources | has("ephemeralStorage") | not) or
 .properties.template.containers[0].resources.ephemeralStorage == "1Gi") and
absent_or_empty_array(.properties.template.containers[0]; "probes") and
absent_or_empty_array(.properties.template.containers[0]; "volumeMounts") and
(.properties.template.containers[0].env | type) == "array" and
(.properties.template.containers[0].env | length) == 21 and
env("COSMAS_ENV") == {name: "COSMAS_ENV", value: "early_adopter_beta"} and
env("DATA_MODE") == {name: "DATA_MODE", value: "synthetic"} and
env("AUTH_MODE") == {name: "AUTH_MODE", value: "clerk_jwt"} and
env("CORS_ALLOWED_ORIGINS") == {name: "CORS_ALLOWED_ORIGINS", value: $web_origin} and
env("SYNTH_SEED") == {name: "SYNTH_SEED", value: "false"} and
env("BLOB_BACKEND") == {name: "BLOB_BACKEND", value: "azure"} and
env("BETA_BOX_ID") == {name: "BETA_BOX_ID", value: $box_id} and
env("CLERK_ORGANIZATION_ID") == {name: "CLERK_ORGANIZATION_ID", value: $clerk_org} and
env("CLERK_ISSUER") == {name: "CLERK_ISSUER", value: $clerk_issuer} and
env("CLERK_JWKS_URL") == {name: "CLERK_JWKS_URL", value: $clerk_jwks} and
env("CLERK_AUDIENCE") == {name: "CLERK_AUDIENCE", value: $clerk_audience} and
env("CLERK_AUTHORIZED_PARTIES") == {name: "CLERK_AUTHORIZED_PARTIES", value: $web_origin} and
env("AZURE_CLIENT_ID") == {name: "AZURE_CLIENT_ID", value: $client_id} and
env("EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID") == {
  name: "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID",
  value: $client_id
} and
env("COSMAS_ACCEPTANCE_HMAC_KEY") == {
  name: "COSMAS_ACCEPTANCE_HMAC_KEY",
  secretRef: "acceptance-hmac-key"
} and
env("HUMAN_DEPLOY_EVIDENCE_REF") == {
  name: "HUMAN_DEPLOY_EVIDENCE_REF",
  secretRef: "human-deploy-evidence-reference"
} and
env("DATABASE_URL") == {name: "DATABASE_URL", secretRef: "database-url"} and
env("REDIS_URL") == {name: "REDIS_URL", secretRef: "redis-url"} and
env("AZURE_STORAGE_ACCOUNT_URL") == {
  name: "AZURE_STORAGE_ACCOUNT_URL",
  value: $blob_url
} and
env("AZURE_BLOB_CONTAINER") == {
  name: "AZURE_BLOB_CONTAINER",
  value: $blob_container
} and
env("SYNC_WORKER") == {name: "SYNC_WORKER", value: "false"}
