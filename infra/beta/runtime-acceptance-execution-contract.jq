def absent_or_empty_array($object; $key):
  ($object | has($key) | not) or
  (($object[$key] | type) == "array" and ($object[$key] | length) == 0);

(.id | ascii_downcase) == $execution_id and
.properties.status == "Succeeded" and
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
absent_or_empty_array(.properties.template.containers[0]; "probes") and
absent_or_empty_array(.properties.template.containers[0]; "volumeMounts") and
(.properties.template.containers[0].env | type) == "array" and
.properties.template.containers[0].resources.cpu == 0.25 and
.properties.template.containers[0].resources.memory == "0.5Gi" and
((.properties.template.containers[0].resources | keys) - [
  "cpu",
  "ephemeralStorage",
  "memory"
] | length) == 0 and
((.properties.template.containers[0].resources | has("ephemeralStorage") | not) or
 .properties.template.containers[0].resources.ephemeralStorage == "1Gi") and
([.properties.template.containers[0] | {
  name,
  image,
  command,
  args,
  env: (.env | sort_by(.name)),
  resources
}]) == ([$requested[0].template.containers[0] | {
  name,
  image,
  command,
  args,
  env: (.env | sort_by(.name)),
  resources
}])
