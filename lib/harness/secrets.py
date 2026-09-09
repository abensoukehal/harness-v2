import re

FLOOR = 8  # a shorter value is not a secret, and substituting it shreds every ordinary line that happens to contain it (9.3)


def too_short(secrets):
    """Keys whose value is under the floor. Setup names them and refuses; it never runs with a scrubber that cannot cover them."""
    return sorted(k for k, v in secrets.items() if 0 < len(v) < FLOOR)


def load_env_file(path):
    values = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


class Scrubber:
    def __init__(self, secrets):
        # An empty value substitutes at every token boundary and shreds the line; the floor itself is enforced
        # once, where the secrets are loaded, and never again here.
        pairs = [(v, k) for k, v in secrets.items() if v]
        self.pairs = sorted(pairs, key=lambda p: -len(p[0]))

    def scrub(self, text):
        # On a token boundary only: a value that is part of a longer word is not the secret, and redacting it there
        # eats the path or identifier around it.
        for value, key in self.pairs:
            text = re.sub(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(value), "[REDACTED %s]" % key, text)
        return text
