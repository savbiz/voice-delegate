"""Refresh the reviewed local documentation snapshot; never fetch arbitrary URLs."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["docs/architecture.md", "docs/m2.md", "docs/m3.md", "docs/m5.md"]
entries = []
for name in FILES:
    text = (ROOT / name).read_text()
    title = text.splitlines()[0].lstrip("# ")
    section = title
    for part in re.split(r"(?m)^(## .+)$", text):
        if part.startswith("## "):
            section = part.strip("# \n")
            continue
        for paragraph in part.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph or paragraph.startswith("# "):
                continue
            # Keep exact contiguous source text, splitting only exceptionally long paragraphs.
            for start in range(0, len(paragraph), 1600):
                content = paragraph[start : start + 1600]
                digest = hashlib.sha256(
                    (name + "\n" + section + "\n" + content).encode()
                ).hexdigest()
                entries.append(
                    dict(
                        id=digest[:16],
                        title=title,
                        path=name,
                        section=section,
                        text=content,
                        digest=digest,
                    )
                )
(ROOT / "agent/src/voice_delegate_agent/data/reference.json").write_text(
    json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
)
print(f"Bundled {len(entries)} source excerpts from {len(FILES)} public project documents.")
