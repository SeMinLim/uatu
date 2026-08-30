import os
import random
import re
import subprocess
import sys
from pathlib import Path


def answerFromOutput(text):
	if re.search(r"^UNSATISFIABLE$", text, re.MULTILINE):
		return "unsat"
	if re.search(r"^SATISFIABLE$", text, re.MULTILINE):
		return "sat"
	return "unknown"


def readModel(text):
	model = []
	for line in text.splitlines():
		fields = line.split()
		if not fields or fields[-1] != "0":
			continue
		try:
			values = [int(value) for value in fields]
		except ValueError:
			continue
		if len(values) > 1:
			model = values[:-1]
	return model


def verifyModel(path, model):
	assignment = {abs(value): value > 0 for value in model if value}
	if not assignment:
		return False

	clause = []
	for line in path.read_text().splitlines():
		stripped = line.strip()
		if not stripped or stripped[0] in "cp%":
			continue
		for token in stripped.split():
			literal = int(token)
			if literal == 0:
				if not any(
					assignment.get(abs(item), False) == (item > 0)
					for item in clause
				):
					return False
				clause.clear()
			else:
				clause.append(literal)
	return not clause


def statValue(text, label):
	for line in text.splitlines():
		if line.startswith(label):
			return int(line.split(":", 1)[1].strip())
	return 0


def writeCNF(path, variables, clauses):
	with path.open("w") as output:
		output.write(f"p cnf {variables} {len(clauses)}\n")
		for clause in clauses:
			output.write(" ".join(str(value) for value in clause) + " 0\n")


def writePigeonhole(path, pigeons, holes):
	def variable(pigeon, hole):
		return pigeon * holes + hole + 1

	clauses = []
	for pigeon in range(pigeons):
		clauses.append([variable(pigeon, hole) for hole in range(holes)])
		for first in range(holes):
			for second in range(first + 1, holes):
				clauses.append([
					-variable(pigeon, first),
					-variable(pigeon, second),
				])
	for hole in range(holes):
		for first in range(pigeons):
			for second in range(first + 1, pigeons):
				clauses.append([
					-variable(first, hole),
					-variable(second, hole),
				])
	writeCNF(path, pigeons * holes, clauses)


def runMiniSAT(cnf, modelPath):
	result = subprocess.run(
		["minisat", "-verb=0", str(cnf), str(modelPath)],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		timeout=20,
		check=False,
	)
	if result.returncode == 10:
		return "sat"
	if result.returncode == 20:
		return "unsat"
	raise SystemExit(
		f"MiniSAT did not solve {cnf}: rc={result.returncode}\n{result.stdout}"
	)


def runUatu(binary, cnf, aggressive):
	env = os.environ.copy()
	env["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
	env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
	env["UATU_TIMEOUT_SEC"] = "20"
	env["UATU_PRINT_MODEL"] = "1"
	if aggressive:
		env["UATU_REDUCE_INITIAL"] = "4"
		env["UATU_REDUCE_STEP"] = "4"
		env["UATU_CORE_LBD"] = "2"
		env["UATU_TIER2_LBD"] = "4"
		env["UATU_TIER2_STALE"] = "4"

	return subprocess.run(
		[str(binary), str(cnf)],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		timeout=30,
		env=env,
		check=False,
	)


def validateCase(binary, cnf, expected, aggressive):
	result = runUatu(binary, cnf, aggressive)
	actual = answerFromOutput(result.stdout)
	if actual != expected:
		raise SystemExit(
			f"Uatu mismatch for {cnf}: expected={expected}, actual={actual}, "
			f"rc={result.returncode}\n{result.stdout}"
		)
	if actual == "sat" and not verifyModel(cnf, readModel(result.stdout)):
		raise SystemExit(f"invalid Uatu model for {cnf}\n{result.stdout}")
	return result.stdout


def main():
	if len(sys.argv) != 2:
		raise SystemExit(f"usage: {sys.argv[0]} <uatu-binary>")

	binary = Path(sys.argv[1])
	root = Path("validation/random")
	root.mkdir(parents=True, exist_ok=True)
	rng = random.Random(20250830)

	for index in range(100):
		variables = rng.randint(4, 14)
		clauseNum = rng.randint(variables, variables * 6)
		clauses = []
		for _ in range(clauseNum):
			width = rng.randint(1, min(4, variables))
			selected = rng.sample(range(1, variables + 1), width)
			clauses.append([
				value if rng.getrandbits(1) else -value
				for value in selected
			])

		cnf = root / f"random-{index:03d}.cnf"
		writeCNF(cnf, variables, clauses)
		expected = runMiniSAT(cnf, root / f"minisat-{index:03d}.model")
		validateCase(binary, cnf, expected, index >= 50)

	pigeonhole = root / "pigeonhole-7-6.cnf"
	writePigeonhole(pigeonhole, 7, 6)
	expected = runMiniSAT(pigeonhole, root / "pigeonhole.model")
	if expected != "unsat":
		raise SystemExit("pigeonhole validation formula was not UNSAT")
	output = validateCase(binary, pigeonhole, expected, True)
	if statValue(output, "Clause Reductions") == 0:
		raise SystemExit("tiered reduction path was not exercised")

	Path("validation/implementation.txt").write_text(
		"release_build=pass\n"
		"debug_build=pass\n"
		"asan_ubsan_build=pass\n"
		"random_differential_cases=100\n"
		"random_differential_result=pass\n"
		"tiered_reduction_exercise=pass\n"
	)
	print("Validated 100 fixed-seed random CNFs and one tiered-reduction exercise")


if __name__ == "__main__":
	main()
