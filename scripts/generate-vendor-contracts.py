"""Regenerate public browser contracts from the Python models; no service access."""

import argparse
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema

from cosmas_os.api import vendor_retirement_schemas as retirement
from cosmas_os.api import vendor_setup_schemas as setup
from cosmas_os.api import vendor_work_schemas as work

ROOT = Path(__file__).resolve().parents[1]
RULES = {"_uuid", "_text", "_day", "_timestamp", "_true", "_version"}


class BrowserSchema(GenerateJsonSchema):
    def function_before_schema(self, schema):
        result = super().function_before_schema(schema)
        name = schema["function"]["function"].__name__
        if name in RULES:
            result = {**result, "x-rules": [*result.get("x-rules", []), name]}
        return result

    def model_schema(self, schema):
        result = super().model_schema(schema)
        return {**result, "x-no-null": issubclass(schema["cls"], work.Closed)}


def models(module):
    return {name: value for name, value in vars(module).items()
            if isinstance(value, type) and issubclass(value, BaseModel)
            and value.__module__ == module.__name__}


def schema_models(modules, *, sort=False):
    selected = {name: model for module in modules for name, model in models(module).items()}
    if sort:
        selected = dict(sorted(selected.items()))
    result = {}
    for name, model in selected.items():
        value = model.model_json_schema(schema_generator=BrowserSchema)
        value.pop("$defs", None)
        result[name] = value
    return result


def typescript(schema, *, no_null=False):
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])
    if "anyOf" in schema or "oneOf" in schema:
        values = schema.get("anyOf", schema.get("oneOf"))
        return " | ".join(typescript(value) for value in values
                          if not no_null or value.get("type") != "null")
    kind = schema.get("type")
    if kind == "object":
        properties, required = schema.get("properties", {}), schema.get("required", [])
        fields = [f'{json.dumps(key)}{"" if key in required else "?"}: '
                  + typescript(value, no_null=schema.get("x-no-null", False))
                  for key, value in properties.items()]
        return "{ " + "; ".join(fields) + " }"
    if kind == "array":
        return "Array<" + typescript(schema["items"]) + ">"
    if kind in {"string", "boolean", "null"}:
        return kind
    if kind in {"integer", "number"}:
        return "number"
    raise ValueError("Unsupported public schema shape: " + repr(schema))


def render(modules, prefix, contract, *, sort=False):
    values = schema_models(modules, sort=sort)
    header = ["// Generated from the existing public Python contract. Do not hand-edit shapes.",
              f"// Relational checks and exact commitments are in {contract}.ts."]
    for index, module in enumerate(modules):
        label = "Retirement source" if index else "Source"
        header.append(f"// {label} SHA-256: " + hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
    alias = "VendorSetupContract" if prefix == "VENDOR_SETUP" else "VendorContract"
    declarations = [f"export type {name} = {typescript(value)};" for name, value in values.items()]
    declarations.append(f"export type {alias}Types = {{ " + "; ".join(f"{name}: {name}" for name in values) + " };")
    declarations.append(f"export type {alias}Name = keyof {alias}Types;")
    return "\n".join(header) + f"\nexport const {prefix}_SCHEMAS = " + json.dumps(values, indent=2) + " as const;\n\n" + "\n".join(declarations) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "web/src")
    options = parser.parse_args()
    outputs = {
        "vendor-schema.ts": render((work, retirement), "VENDOR", "vendor-contract"),
        "vendor-setup-schema.ts": render((setup,), "VENDOR_SETUP", "vendor-setup-contract", sort=True),
    }
    for name, content in outputs.items():
        path = options.output / name
        if options.check:
            if path.read_text() != content:
                raise SystemExit(name + " is stale; regenerate the public contracts")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)


if __name__ == "__main__":
    main()
