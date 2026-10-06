"""Regenerate CLOUDVAULT_FULL_SPEC.md from AGENTS.md, README.md and docs/NN-*.md.

Run from the repo root: python3 tools/build_full_spec.py
Relative links inside docs/ are rewritten to be relative to the repo root.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = (
    "# CloudVault: Full Specification (single file)\n\n"
    "> Concatenation of `AGENTS.md`, `README.md` and `docs/01` to `docs/{last}`. "
    "Diagram images are referenced from `docs/diagrams/`.\n"
)
LINK = re.compile(r"\]\((?!https?://|#|docs/|/)([^)]+)\)")


def main() -> None:
    docs = sorted(p for p in (ROOT / "docs").glob("[0-9][0-9]-*.md"))
    parts = [(ROOT / "AGENTS.md").read_text().strip(), (ROOT / "README.md").read_text().strip()]
    parts += [LINK.sub(r"](docs/\1)", p.read_text().strip()) for p in docs]
    last = docs[-1].name[:2]
    out = HEADER.format(last=last) + "\n\n---\n\n" + "\n\n---\n\n".join(parts) + "\n"
    (ROOT / "CLOUDVAULT_FULL_SPEC.md").write_text(out)
    print(f"Wrote CLOUDVAULT_FULL_SPEC.md from {len(parts)} files")


if __name__ == "__main__":
    main()
