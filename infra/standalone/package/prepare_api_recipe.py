"""Compose the existing pinned API build and standalone launcher, without Docker I/O."""

import argparse
import hashlib
import json
from pathlib import Path


def prepare(source: Path, output: Path):
    source = source.resolve(strict=True)
    if output.exists() or not output.is_absolute():
        raise ValueError("Use a new absolute output directory")
    names = ["Dockerfile", ".dockerignore", "infra/standalone/package/Dockerfile.api.fragment",
             "infra/standalone/package/entrypoint.py"]
    content = {}
    for name in names:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Use regular reviewed package inputs")
        content[name] = path.read_bytes()
    output.mkdir(mode=0o700)
    recipe = content["Dockerfile"].rstrip() + b"\n" + content[names[2]]
    ignores = content[".dockerignore"].rstrip() + b"\n!infra/\n!infra/standalone/\n!infra/standalone/package/\n!infra/standalone/package/entrypoint.py\n"
    (output / "Dockerfile").write_bytes(recipe)
    (output / "Dockerfile.dockerignore").write_bytes(ignores)
    receipt = {"source": str(source), "inputs": {name: hashlib.sha256(data).hexdigest()
               for name, data in content.items()}, "generated": {
               "Dockerfile": hashlib.sha256(recipe).hexdigest(),
               "Dockerfile.dockerignore": hashlib.sha256(ignores).hexdigest()},
               "architecture": "linux/amd64", "docker_called": False}
    (output / "recipe.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.source, args.output)
    print("Prepared standalone API recipe; no image was built or published.")
