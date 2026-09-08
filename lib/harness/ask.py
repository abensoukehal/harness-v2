"""The ask format (13, 20.5): what Ali reads on a phone when the run needs an answer."""


def render(ask):
    lines = [ask["where"], "", ask["stuck"], ""]
    if ask["tried"]:
        lines += ["Tried: " + t for t in ask["tried"]] + [""]
    lines.append(ask["question"])
    lines += ["%s. %s%s" % (o["letter"], o["text"], " (recommended)" if o["recommended"] else "") for o in ask["options"]]
    lines += ["", "Still running: " + ask["still_running"], "Detail: " + ask["detail"]]
    return "\n".join(lines) + "\n"
