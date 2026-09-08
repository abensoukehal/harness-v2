#!/usr/bin/env bash
# Mechanical hygiene check (14.4, 20.1, 14.2). Every hit fails. No judgement anywhere in here.
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
  [ $# -eq 0 ] && return 0
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

harness_files=()
while IFS= read -r -d '' f; do harness_files+=("$f"); done < <(
  find "$harness" -type f ! -path '*/.git/*' ! -path '*/node_modules/*' ! -name package-lock.json \
       ! -name harness-v2-spec.md ! -name hygiene.sh ! -name .DS_Store -print0)
scan date   "$date_rx"   "" "${harness_files[@]}"
scan ticket "$ticket_rx" "" "${harness_files[@]}"
scan words  "$words_rx"  -i "${harness_files[@]}"

if [ -n "$workspace" ]; then
  names=$(python3 - "$workspace/product/client.config.yaml" <<'PY'
import re, sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
generic = {"frontend", "backend", "mobile", "ai", "web", "api", "app", "db"}
names = {c["client"]} | set(c["stacks"]) | {s["repo"] for s in c["stacks"].values()}
print("|".join(re.escape(n) for n in sorted(names) if n not in generic))
PY
  ) || { echo "cannot read $workspace/product/client.config.yaml" >&2; exit 2; }
  [ -n "$names" ] && scan client "\b($names)\b" -i "${harness_files[@]}"
  product_files=()
  while IFS= read -r -d '' f; do product_files+=("$f"); done < <(
    find "$workspace/product/conventions.md" "$workspace/product/code-map" -type f ! -name .gitkeep -print0 2>/dev/null)
  scan date   "$date_rx"   "" "${product_files[@]}"
  scan ticket "$ticket_rx" "" "${product_files[@]}"
  scan words  "$words_rx"  -i "${product_files[@]}"
fi
exit $fail
