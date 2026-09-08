MIN_LEN = 4  # ponytail: shorter values are not secrets and would shred ordinary output


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
        pairs = [(v, k) for k, v in secrets.items() if len(v) >= MIN_LEN]
        self.pairs = sorted(pairs, key=lambda p: -len(p[0]))

    def scrub(self, text):
        for value, key in self.pairs:
            text = text.replace(value, "[REDACTED %s]" % key)
        return text
