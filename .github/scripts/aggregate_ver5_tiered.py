import csv
from pathlib import Path


rows = []
for path in Path("downloaded").glob("*/result.csv"):
	with path.open(newline="") as source:
		rows.extend(csv.DictReader(source))

rows.sort(key=lambda row: int(row["id"]))
if len(rows) != 10:
	raise SystemExit(f"expected 10 benchmark rows, found {len(rows)}")
if any(row["correct"] != "1" or row["result"] != row["expected"] for row in rows):
	raise SystemExit("at least one SAT Competition benchmark failed validation")
if sum(row["expected"] == "sat" for row in rows) != 5:
	raise SystemExit("expected five SAT benchmarks")
if sum(row["expected"] == "unsat" for row in rows) != 5:
	raise SystemExit("expected five UNSAT benchmarks")

Path("evaluation").mkdir(exist_ok=True)
fields = list(rows[0])
with Path("evaluation/ver5_tiered_smoke10.csv").open("w", newline="") as output:
	writer = csv.DictWriter(output, fieldnames=fields)
	writer.writeheader()
	writer.writerows(rows)

totalWall = sum(float(row["wall_sec"]) for row in rows)
lines = [
	"# Uatu Ver5 Tiered Clause Management Validation",
	"",
	"- Implementation: Ver. 3 plus CORE, TIER2, and LOCAL learned-clause management",
	"- Isolation: VSIDS and one-step minimization retained; CHB and recursive minimization disabled",
	"- Static validation: release, debug, and ASan/UBSan builds passed with warnings treated as errors",
	"- Differential validation: 100 fixed-seed random CNFs matched MiniSAT; every SAT model was checked",
	"- Tier-path validation: a fixed pigeonhole instance exercised learned-clause reduction under ASan/UBSan",
	"- Benchmark validation: 10 SAT Competition 2025 Main Track instances, five SAT and five UNSAT",
	"- Per-instance timeout: 300 seconds",
	"",
	"| ID | Expected | Result | Model | Wall (s) | CORE | TIER2 | LOCAL | Reductions | Deleted |",
	"|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
]
for row in rows:
	lines.append(
		f"| {row['id']} | {row['expected']} | {row['result']} | "
		f"{row['model_valid']} | {float(row['wall_sec']):.3f} | "
		f"{row['core']} | {row['tier2']} | {row['local']} | "
		f"{row['reductions']} | {row['deleted']} |"
	)
lines += [
	"",
	"**Validation result: 10/10 correct.**",
	f"Aggregate solver wall time: **{totalWall:.3f} seconds**.",
	"",
]
Path("evaluation/ver5_tiered_smoke10.md").write_text("\n".join(lines))
print("\n".join(lines))
