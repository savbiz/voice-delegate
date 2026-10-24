"""Render installed dependency licences without rewriting upstream legal text."""

import argparse
import hashlib
import json
import re
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEGAL_NAME = re.compile(r"^(licen[sc]e|notice|copying|copyright)(?:[._-]|$)", re.I)


def block(text: str) -> str:
    fence = "`" * max(4, max((len(m[0]) + 1 for m in re.finditer(r"`+", text)), default=4))
    return f"{fence}text\n{text.rstrip()}\n{fence}\n"


def section(name: str, version: str, licence: str, texts: dict[str, str]) -> str:
    if not texts:
        raise ValueError("Missing licence text for " + name)
    parts = [f"### `{name}` {version}\n\nLicence: {licence}.\n"]
    for source, text in texts.items():
        parts.append(f"Source: {source}\n\n{block(text)}")
    return "\n".join(parts)


def python_texts(row: dict[str, Any]) -> dict[str, str]:
    texts: dict[str, str] = {}
    # Inspect all distribution files as pip-licenses can select only one licence file.
    try:
        dist = distribution(row["Name"])
    except PackageNotFoundError:
        base = Path(row["LicenseFile"]).parent
        files = list(base.glob("*"))
    else:
        base = Path(str(dist.locate_file("")))
        files = [Path(str(dist.locate_file(f))) for f in dist.files or []]
    for file in sorted(files):
        if file.is_file() and LEGAL_NAME.match(file.name):
            texts[str(file.relative_to(base))] = file.read_text()
    for kind in ("License", "Notice"):
        text = row.get(kind + "Text", "UNKNOWN")
        if text != "UNKNOWN" and text not in texts.values():
            texts["pip-licenses " + kind] = text
    if row["Name"] in {"voice-delegate", "voice-delegate-agent"}:
        texts["project LICENSE"] = (ROOT / "LICENSE").read_text()
        texts["project NOTICE"] = (ROOT / "NOTICE").read_text()
    return texts


def frontend_texts(path: Path) -> dict[str, str]:
    texts = {
        str(file.relative_to(path)): file.read_text()
        for file in sorted(path.rglob("*"))
        if file.is_file()
        and "node_modules" not in file.relative_to(path).parts
        and LEGAL_NAME.match(file.name)
    }
    if not texts:
        # Some packages ship their full licence only in the README.
        for file in path.glob("*README*"):
            text = file.read_text()
            match = re.search(r"(?im)^(?:#+ )?License(?: \(MIT\))?\s*$", text)
            if match and len(text[match.start() :].split()) > 100:
                texts[file.name + " licence section"] = text[match.start() :]
    return texts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-inventory", type=Path, required=True)
    parser.add_argument("--build-inventory", type=Path, required=True)
    parser.add_argument("--frontend-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "THIRD_PARTY_NOTICES.md")
    args = parser.parse_args()
    supplements = json.loads((ROOT / "scripts/licenses/supplements.json").read_text())
    python = json.loads(args.python_inventory.read_text())
    python += json.loads(args.build_inventory.read_text())
    frontend = json.loads(args.frontend_inventory.read_text())
    if "error" in frontend:
        message = "pnpm licence inventory failed; repair installation before generating"
        raise ValueError(message)
    parts = [
        "# Third-party notices\n\n"
        "Generated from pip-licenses and pnpm licenses list --long. "
        "This inventory covers the installed Python runtime and frontend dependencies, "
        "It also includes development, build, test and optional evaluation tools for transparency. "
        "Listing a tool does not mean it is shipped in the browser or backend container. "
        "Native build-tool bindings reflect the inventory platform (macOS arm64). "
        "Upstream licence and NOTICE texts are reproduced below without modification. "
        "See scripts/licenses/README.md for regeneration and supplemental sources.\n\n## Python\n"
    ]
    for row in sorted(python, key=lambda row: row["Name"].lower()):
        name = row["Name"]
        texts = python_texts(row)
        if not texts and name in supplements:
            extra = supplements[name]
            texts[extra["source"]] = extra["text"]
        parts.append(section(name, row["Version"], row["License"], texts))
    parts.append("## Frontend\n")
    for row in sorted(
        [row for group in frontend.values() for row in group], key=lambda r: r["name"]
    ):
        for path in row["paths"]:
            package = json.loads((Path(path) / "package.json").read_text())
            texts = frontend_texts(Path(path))
            if not texts and row["name"] in supplements:
                extra = supplements[row["name"]]
                texts[extra["source"]] = extra["text"]
            parts.append(section(row["name"], package["version"], row["license"], texts))
    data = ROOT / "backend/src/voice_delegate/limits/data/o200k_base.tiktoken"
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    parts.append(
        "## Bundled data\n\n"
        "File: backend/src/voice_delegate/limits/data/o200k_base.tiktoken\n\n"
        "Source project: tiktoken (OpenAI), https://github.com/openai/tiktoken.\n\n"
        "Licence: MIT, as reproduced in limits/data/LICENSE.tiktoken.\n\n"
        "Original download URL: "
        "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken\n\n"
        f"SHA-256: `{digest}`\n\n"
        "Redistributed unmodified under the terms of the tiktoken MIT licence.\n\n"
        + block(data.with_name("LICENSE.tiktoken").read_text())
    )
    parts.append((ROOT / "scripts/licenses/container-tooling.md").read_text())
    args.output.write_text("\n".join(parts))


if __name__ == "__main__":
    main()
