#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE="$SCRIPT_DIR/benchmark.tar.gz"
OUTPUT_DIR="$SCRIPT_DIR/cnf"

if [[ ! -f "$ARCHIVE" ]]; then
    echo "error: archive not found: $ARCHIVE" >&2
    exit 1
fi

for tool in tar find; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: required command not found: $tool" >&2
        exit 1
    fi
done

mkdir -p "$OUTPUT_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

tar -xzf "$ARCHIVE" -C "$TMP_DIR"

count=0
while IFS= read -r -d '' source; do
    name="$(basename "$source")"
    install -m 0644 "$source" "$OUTPUT_DIR/$name"
    count=$((count + 1))
done < <(find "$TMP_DIR" -type f -name '*.cnf' -print0)

while IFS= read -r -d '' source; do
    if ! command -v xz >/dev/null 2>&1; then
        echo "error: xz is required because the archive contains .cnf.xz files" >&2
        exit 1
    fi
    name="$(basename "${source%.xz}")"
    tmp_output="$OUTPUT_DIR/.${name}.tmp.$$"
    xz -dc -- "$source" > "$tmp_output"
    mv -f -- "$tmp_output" "$OUTPUT_DIR/$name"
    count=$((count + 1))
done < <(find "$TMP_DIR" -type f -name '*.cnf.xz' -print0)

if [[ $count -eq 0 ]]; then
    echo "error: no .cnf or .cnf.xz files were found in $ARCHIVE" >&2
    exit 1
fi

echo "Extracted $count sample benchmark(s) into: $OUTPUT_DIR"
