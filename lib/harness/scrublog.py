"""stdin -> file, every line scrubbed. Runs as its own process so the stack outlives bin/up.
usage: scrublog.py <logfile> KEY...   values are read from this process's environment, never from argv."""
import os
import sys

from secrets import Scrubber  # noqa: E402  (sibling module; sys.path[0] is this directory)


def main():
    logfile, keys = sys.argv[1], sys.argv[2:]
    scrubber = Scrubber({k: os.environ.get(k, "") for k in keys})
    with open(logfile, "a", buffering=1) as out:
        for raw in sys.stdin.buffer:
            out.write(scrubber.scrub(raw.decode("utf-8", "replace")))


if __name__ == "__main__":
    main()
