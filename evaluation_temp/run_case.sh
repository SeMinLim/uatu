#!/usr/bin/env bash
set -euo pipefail

INDEX="$1"
EXPECTED="$2"
BENCHMARK_HASH="$3"
BENCHMARK_URL="$4"
TIMEOUT_SEC=1000

mkdir -p work result
curl -fL --retry 8 --retry-delay 5 "$BENCHMARK_URL" -o work/instance.cnf.xz
xz -t work/instance.cnf.xz
xz -dc work/instance.cnf.xz > work/instance.cnf

total_mem_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
reserve_mem_kb=2097152
if (( total_mem_kb > reserve_mem_kb + 1048576 )); then
	memory_limit_kb=$((total_mem_kb - reserve_mem_kb))
else
	memory_limit_kb=$((total_mem_kb * 70 / 100))
fi

output=work/ver4.out
timing=work/ver4.time
command="ulimit -v ${memory_limit_kb}; exec env UATU_TIMEOUT_SEC=${TIMEOUT_SEC} UATU_PRINT_MODEL=1 cpu/ver_4/obj/uatu_solver work/instance.cnf"

set +e
/usr/bin/time -q -f '%e,%U,%S,%M' -o "$timing" \
	timeout --signal=TERM --kill-after=5s "$((TIMEOUT_SEC + 10))s" \
	bash -lc "$command" > "$output" 2>&1
rc=$?
set -e

answer=error
if grep -qx 'UNSATISFIABLE' "$output"; then
	answer=unsat
elif grep -qx 'SATISFIABLE' "$output"; then
	answer=sat
elif grep -qx 'UNSOLVED' "$output" || \
     grep -q 'INDETERMINATE' "$output" || \
     [[ $rc -eq 124 || $rc -eq 137 || $rc -eq 143 ]]; then
	answer=timeout
fi

model_valid=1
if [[ "$answer" == sat ]]; then
	set +e
	python3 evaluation_temp/verify_model.py "$output" work/instance.cnf
	verify_rc=$?
	set -e
	if [[ $verify_rc -ne 0 ]]; then model_valid=0; fi
fi

correct=0
if [[ "$answer" == "$EXPECTED" && $model_valid -eq 1 ]]; then
	correct=1
fi

wall="$((TIMEOUT_SEC + 10))"
user=0
sys=0
rss=0
if [[ -s "$timing" ]]; then
	IFS=',' read -r wall user sys rss < "$timing" || true
fi

vivify_runs=$(awk -F: '/^Vivification Runs/ {gsub(/[[:space:]]/, "", $2); print $2; exit}' "$output")
vivified_clauses=$(awk -F: '/^Vivified Clauses/ {gsub(/[[:space:]]/, "", $2); print $2; exit}' "$output")
vivified_literals=$(awk -F: '/^Vivified Literals/ {gsub(/[[:space:]]/, "", $2); print $2; exit}' "$output")
vivify_runs=${vivify_runs:-0}
vivified_clauses=${vivified_clauses:-0}
vivified_literals=${vivified_literals:-0}

printf 'index,expected,solver,result,correct,model_valid,wall_sec,user_sec,sys_sec,rss_kb,exit_code,hash,vivification_runs,vivified_clauses,vivified_literals,url\n' > result/result.csv
printf '%s,%s,ver4,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
	"$INDEX" "$EXPECTED" "$answer" "$correct" "$model_valid" \
	"$wall" "$user" "$sys" "$rss" "$rc" "$BENCHMARK_HASH" \
	"$vivify_runs" "$vivified_clauses" "$vivified_literals" "$BENCHMARK_URL" \
	>> result/result.csv
cat result/result.csv
if [[ "$answer" == error || $model_valid -eq 0 ]]; then
	printf '%s\n' '----- solver output -----'
	tail -200 "$output" || true
fi
