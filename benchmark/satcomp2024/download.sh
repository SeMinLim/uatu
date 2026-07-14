#!/usr/bin/env bash
set -euo pipefail

YEAR=2024
TRACK="main_${YEAR}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URI_FILE="$SCRIPT_DIR/track_main_${YEAR}.uri"
COMPRESSED_DIR="$SCRIPT_DIR/compressed"
CNF_DIR="$SCRIPT_DIR/cnf"
URI_URL="https://benchmark-database.de/?track=${TRACK}&context=cnf"

usage() {
    cat <<EOF
Usage: bash download.sh [download|extract|all]

  download  Download the URI manifest and compressed .cnf.xz instances.
  extract   Decompress downloaded instances into ./cnf.
  all       Perform download and extraction (default).
EOF
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "error: required command not found: $1" >&2
        exit 1
    fi
}

download_manifest() {
    if [[ -s "$URI_FILE" ]] && grep -qE '^https?://' "$URI_FILE"; then
        return
    fi

    require_command wget
    tmp_file="$URI_FILE.tmp.$$"
    rm -f "$tmp_file"
    wget -O "$tmp_file" "$URI_URL"

    if ! grep -qE '^https?://' "$tmp_file"; then
        rm -f "$tmp_file"
        echo "error: the downloaded manifest did not contain benchmark URLs" >&2
        echo "Download track_main_${YEAR}.uri manually from: $URI_URL" >&2
        exit 1
    fi

    mv -f "$tmp_file" "$URI_FILE"
}

download_instances() {
    require_command wget
    download_manifest
    mkdir -p "$COMPRESSED_DIR"
    (
        cd "$COMPRESSED_DIR"
        wget --content-disposition --continue -i "$URI_FILE"
    )
    count="$(find "$COMPRESSED_DIR" -maxdepth 1 -type f -name '*.cnf.xz' | wc -l)"
    echo "Downloaded $count compressed benchmark(s) into: $COMPRESSED_DIR"
}

extract_instances() {
    require_command xz
    mkdir -p "$CNF_DIR"
    mapfile -d '' files < <(find "$COMPRESSED_DIR" -maxdepth 1 -type f -name '*.cnf.xz' -print0 2>/dev/null || true)

    if [[ ${#files[@]} -eq 0 ]]; then
        echo "error: no .cnf.xz files found; run 'bash download.sh download' first" >&2
        exit 1
    fi

    extracted=0
    skipped=0
    for source in "${files[@]}"; do
        name="$(basename "${source%.xz}")"
        destination="$CNF_DIR/$name"
        if [[ -s "$destination" ]]; then
            skipped=$((skipped + 1))
            continue
        fi
        tmp_output="$CNF_DIR/.${name}.tmp.$$"
        xz -dc -- "$source" > "$tmp_output"
        mv -f -- "$tmp_output" "$destination"
        extracted=$((extracted + 1))
    done

    total="$(find "$CNF_DIR" -maxdepth 1 -type f -name '*.cnf' | wc -l)"
    echo "Extracted $extracted benchmark(s); skipped $skipped existing file(s)."
    echo "Decompressed benchmark total: $total in $CNF_DIR"
}

command="${1:-all}"
case "$command" in
    download) download_instances ;;
    extract)  extract_instances ;;
    all)      download_instances; extract_instances ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
esac
