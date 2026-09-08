#!/usr/bin/env bash
# Mechanical hygiene check over prose (14.4, 20.1, 14.2). Every hit fails. No judgement anywhere in here.
# Prose: CLAUDE.md, claude/agents, claude/skills, STATE.md, OPEN_QUESTIONS.md, templates/**/*.md,
# and in a workspace product/conventions.md and product/code-map/. This script is the one exempt file.
# usage: hygiene.sh [--harness DIR] [--workspace DIR]
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
harness=$(dirname "$here")
workspace=""
while [ $# -gt 0 ]; do
  case $1 in
    --harness) harness=$(cd "$2" && pwd); shift 2 ;;
    --workspace) workspace=$(cd "$2" && pwd); shift 2 ;;
    *) echo "usage: hygiene.sh [--harness DIR] [--workspace DIR]" >&2; exit 2 ;;
  esac
done
if [ -z "$workspace" ] && [ -f "$harness/../product/client.config.yaml" ]; then
  workspace=$(cd "$harness/.." && pwd)
fi

months='(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
date_rx="\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b|\b${months} [0-9]{1,2}, [0-9]{4}\b|\b[0-9]{1,2} ${months} [0-9]{4}\b"
ticket_rx='\b[A-Z]{2,}-[0-9]+\b'
ticket_ok='\b(UTF|SHA|ISO|RFC)-[0-9]+'
words_rx='\b(superseded|retired|deprecated|used to|previously|no longer|as of|before (st-[0-9]+|[A-Z]{2,}-[0-9]+))\b'

fail=0
scan() {  # scan <rule> <regex> <grep flags> <files...>
  local rule=$1 rx=$2 flags=$3 hits
  shift 3
  [ $# -eq 0 ] || [ -z "${1:-}" ] && return 0
  hits=$(grep -nHIE $flags -e "$rx" -- "$@" 2>/dev/null)
  if [ "$rule" = ticket ] && [ -n "$hits" ]; then
    hits=$(printf '%s\n' "$hits" | grep -vE "$ticket_ok")
  fi
  if [ -n "$hits" ]; then
    printf '%s\n' "$hits" | sed "s|^|$rule  |"
    fail=1
  fi
  return 0
}
collect() {  # collect <paths...>: prints existing files, NUL-separated; markdown under directories
  local p
  for p in "$@"; do
    if [ -f "$p" ]; then printf '%s\0' "$p"
    elif [ -d "$p" ]; then find "$p" -type f -name '*.md' -print0
    fi
  done
}

prose=()
while IFS= read -r -d '' f; do prose+=("$f"); done < <(
  collect "$harness/CLAUDE.md" "$harness/STATE.md" "$harness/OPEN_QUESTIONS.md" "$harness/claude/agents" "$harness/claude/skills" "$harness/templates")
scan date   "$date_rx"   "" "${prose[@]:-}"
scan ticket "$ticket_rx" "" "${prose[@]:-}"
scan words  "$words_rx"  -i "${prose[@]:-}"

if [ -n "$workspace" ]; then
  names=$(python3 - "$workspace/product/client.config.yaml" <<'PY'
import re, sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
generic = {"frontend", "backend", "mobile", "ai", "web", "api", "app", "db"}
names = {c["client"]} | set(c["stacks"]) | {s["repo"] for s in c["stacks"].values() if s.get("repo")}
print("|".join(re.escape(n) for n in sorted(names) if n not in generic))
PY
  ) || { echo "cannot read $workspace/product/client.config.yaml" >&2; exit 2; }
  [ -n "$names" ] && scan client "\b($names)\b" -i "${prose[@]:-}"
  product=()
  while IFS= read -r -d '' f; do product+=("$f"); done < <(collect "$workspace/product/conventions.md" "$workspace/product/code-map")
  scan date   "$date_rx"   "" "${product[@]:-}"
  scan ticket "$ticket_rx" "" "${product[@]:-}"
  scan words  "$words_rx"  -i "${product[@]:-}"
fi
exit $fail
