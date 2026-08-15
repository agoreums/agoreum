#!/usr/bin/env bash
# Run a command and report *its* exit code, not some later command's.
#
# Why this exists. Three times on 2026-08-15 a result was read from the wrong
# command. `pytest ... | tail -4; echo $?` reports tail's status, which is
# always zero. `tsc --noEmit | tail -2; echo "exit: $?"` did the same while tsc
# was reporting two real errors. A pipeline's reported success can come from the
# wrong command entirely, and it looks exactly like the right one succeeding.
#
# `set -o pipefail` fixes the pipeline case and is easy to forget. This makes
# forgetting impossible for the calling shell: the command runs unpiped, its
# output goes to a file, and the status printed is the one that matters.
#
# Usage:
#   scripts/run-checked.sh pytest --timeout=60
#   scripts/run-checked.sh --tail 20 npx tsc --noEmit -p tsconfig.json
#
# Exits with the wrapped command's status, so it composes in CI as well.

set -u

tail_lines=12
if [ "${1:-}" = "--tail" ]; then
    tail_lines="$2"
    shift 2
fi

if [ "$#" -eq 0 ]; then
    echo "run-checked: nothing to run" >&2
    exit 2
fi

output="$(mktemp)"
trap 'rm -f "$output"' EXIT

# No pipe. The command's status is the script's status, with nothing in between
# that could overwrite it.
"$@" >"$output" 2>&1
status=$?

tail -n "$tail_lines" "$output"

printf '\n--- %s\n' "$(
    if [ "$status" -eq 0 ]; then
        echo "OK: $1 exited 0"
    else
        echo "FAILED: $1 exited $status"
    fi
)"

# Loud about the difference between "no output" and "no run". A command that
# produced nothing and a command that never started look identical otherwise.
if [ ! -s "$output" ]; then
    echo "--- note: the command produced no output at all" >&2
fi

exit "$status"
