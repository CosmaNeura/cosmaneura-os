($job[0].properties.template.containers[0]) as $container |
def base_env: $container.env;
def direct($args): {
  name: $container.name,
  image: $container.image,
  resources: $container.resources,
  command: ["python", "-m", "cosmas_os.cli"],
  args: $args,
  env: base_env
};
def verify($args): {
  name: $container.name,
  image: $container.image,
  resources: $container.resources,
  command: ["python", "-m", "cosmas_os.cli"],
  args: $args,
  env: (base_env + [{name: "COSMAS_ACCEPTANCE_STATE", value: $prior_state_json}])
};
{template: {containers: [
  if $phase == "runtime" then
    direct(["verify-beta-runtime", "--confirm-synthetic-only", "--confirm-runtime-uami"])
  elif $phase == "workflow-baseline" then
    direct(["baseline-beta-workflow-acceptance", "--confirm-synthetic-only", "--confirm-async-worker"])
  elif $phase == "workflow-verify" then
    verify(["verify-beta-workflow-acceptance", "--confirm-synthetic-only", "--confirm-browser-complete"])
  elif $phase == "audit-replay" then
    direct(["verify-beta-audit-replay", "--confirm-synthetic-only", "--confirm-no-content-export"])
  elif $phase == "purge-setup" then
    direct(["prepare-beta-purge-acceptance", "--confirm-synthetic-only", "--confirm-runtime-uami"])
  elif $phase == "purge-verify" then
    verify(["verify-beta-purge-acceptance", "--confirm-synthetic-only", "--confirm-runtime-uami", "--confirm-browser-complete"])
  else
    error("unreviewed acceptance phase")
  end
]}}
