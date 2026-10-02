"""Build the bundled evergreen documentation snapshot without network access."""

import argparse
import hashlib
import json
import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "agent/src/voice_delegate_agent/data/reference.json"


def documents(root: Path) -> list[Path]:
    return [
        root / "README.md",
        root / "docs/architecture.md",
        *sorted((root / "docs/decisions").glob("*.md")),
        root / "docs/local-development.md",
    ]


def excerpts(path: Path, root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    name = path.relative_to(root).as_posix()
    lines = path.read_text().splitlines()
    title = lines[0].lstrip("# ")
    section = title
    paragraph: list[str] = []
    fence = ""
    comment = False

    def flush() -> None:
        content = "\n".join(paragraph).strip()
        paragraph.clear()
        remainder = content
        while True:
            stripped = re.sub(r"!?\[[^\[\]]*\]\([^)]*\)", "", remainder)
            if stripped == remainder:
                break
            remainder = stripped
        if "\n" not in content or not remainder.strip(" \n*-[]"):
            return
        # Break at whitespace; a long unbroken word stays intact.
        for chunk in textwrap.wrap(
            content,
            1600,
            break_long_words=False,
            break_on_hyphens=False,
            replace_whitespace=False,
        ):
            digest = hashlib.sha256(f"{name}\n{section}\n{chunk}".encode()).hexdigest()
            entries.append(
                {
                    "id": digest[:16],
                    "title": title,
                    "path": name,
                    "section": section,
                    "text": chunk,
                    "digest": digest,
                }
            )

    for line in lines:
        if "<!--" in line:
            flush()
            comment = True
        if comment:
            if "-->" in line:
                comment = False
            continue
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            flush()
            delimiter = marker[1]
            if not fence:
                fence = delimiter
            elif delimiter[0] == fence[0] and len(delimiter) >= len(fence):
                fence = ""
            continue
        if fence:
            continue
        if line.startswith("#"):
            flush()
            section = line.lstrip("# ")
        elif not line.strip() or line.startswith("|"):
            flush()
        else:
            if re.match(r"^[-*+] |^\d+\. ", line):
                flush()
            paragraph.append(line)
    flush()
    return entries


def build(root: Path) -> str:
    entries = [entry for path in documents(root) for entry in excerpts(path, root)]
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if the snapshot has drifted")
    args = parser.parse_args()
    rendered = build(ROOT)
    if args.check:
        if not args.output.exists() or args.output.read_text() != rendered:
            message = "Documentation snapshot has drifted; run scripts/build_reference.py"
            raise SystemExit(message)
        print("Documentation snapshot is current.")
    else:
        args.output.write_text(rendered)
        print(f"Bundled {len(json.loads(rendered))} evergreen source excerpts.")


if __name__ == "__main__":
    main()
