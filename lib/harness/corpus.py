"""The instruction corpus (6.1): every character an agent loads, wherever the prose is written.

Markdown under claude/ and the two CLAUDE.md files are the obvious half. The other half is the prompt text built
inside a workflow script, which reaches an agent exactly the way a skill does. Counting only the markdown caps
where prose is filed, not how much of it an agent reads.
"""
import re
from pathlib import Path

FILLED = re.compile(r"\$\{[^{}]*\}")
FLOOR = 25  # a quoted string shorter than this is a key, a label or a status word, not a sentence


def prompt_text(source):
    """The literal prose in one workflow script, with the interpolations taken out.

    Scanned left to right rather than matched: a regex over quoted strings pairs the close of one with the open of
    the next, and counts the code between two short labels as prose.
    """
    out, i, n = [], 0, len(source)
    while i < n:
        c = source[i]
        if c == "/" and source[i:i + 2] == "//":
            i = source.find("\n", i)
            if i < 0:
                break
        elif c == "/" and source[i:i + 2] == "/*":
            end = source.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "`'\"":
            j, body = i + 1, []
            while j < n and source[j] != c:
                if source[j] == "\\" and j + 1 < n:
                    body.append(source[j + 1])
                    j += 2
                    continue
                body.append(source[j])
                j += 1
            text = "".join(body)
            if c == "`" or len(text) >= FLOOR:
                out.append(FILLED.sub("", text))
            i = j + 1
        else:
            i += 1
    return "".join(out)


def files(root):
    root = Path(root)
    return ([root / "CLAUDE.md", root / "templates" / "workspace" / "CLAUDE.md"]
            + sorted((root / "claude").rglob("*.md")) + sorted((root / "claude" / "workflows").glob("*.js")))


def total(root):
    return sum(len(prompt_text(p.read_text()) if p.suffix == ".js" else p.read_text()) for p in files(root) if p.is_file())
