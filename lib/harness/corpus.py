"""The instruction corpus (6.1): every character an agent loads, wherever the prose is written.

Markdown under claude/ and the two CLAUDE.md files are the obvious half. The other half is the prompt text built
inside a workflow script, which reaches an agent exactly the way a skill does. Counting only the markdown caps
where prose is filed, not how much of it an agent reads.
"""
import re
from pathlib import Path

# A prompt is a template literal, or a quoted string long enough to be a sentence. Schema keywords, status words
# and labels fall under the length; prose does not.
LITERAL = re.compile(r"`(?:[^`\\]|\\.)*`|'(?:[^'\\\n]|\\.){25,}'|\"(?:[^\"\\\n]|\\.){25,}\"", re.S)
FILLED = re.compile(r"\$\{[^{}]*\}")


def prompt_text(source):
    """The literal prose in one workflow script, with the interpolations taken out."""
    return "".join(FILLED.sub("", m.group(0))[1:-1] for m in LITERAL.finditer(source))


def files(root):
    root = Path(root)
    return ([root / "CLAUDE.md", root / "templates" / "workspace" / "CLAUDE.md"]
            + sorted((root / "claude").rglob("*.md")) + sorted((root / "claude" / "workflows").glob("*.js")))


def total(root):
    return sum(len(prompt_text(p.read_text()) if p.suffix == ".js" else p.read_text()) for p in files(root) if p.is_file())
