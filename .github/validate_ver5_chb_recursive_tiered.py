import itertools
import os
import random
import re
import subprocess
import sys
from pathlib import Path


def writeCNF(path, variables, clauses):
	with path.open("w") as output:
		output.write(f"p cnf {variables} {len(clauses)}\n")
		for clause in clauses:
			output.write(" ".join(str(literal) for literal in clause) + " 0\n")


def solveBruteForce(variables, clauses):
	for values in itertools.product((False, True), repeat=variables):
		valid = True
		for clause in clauses:
			if not any(values[abs(literal) - 1] == (literal > 0)
			           for literal in clause):
				valid = False
				break
		if valid:
			return "sat"
	return "unsat"


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


def verifyModel(variables, clauses, model):
	assignment = {abs(literal): literal > 0 for literal in model if literal}
	if len(assignment) < variables:
		return False
	for clause in clauses:
		if not any(assignment[abs(literal)] == (literal > 0)
		           for literal in clause):
			return False
	return True


def statistic(text, label):
	pattern = rf"^{re.escape(label)}\s*:\s*([0-9]+)$"
	match = re.search(pattern, text, re.MULTILINE)
	return int(match.group(1)) if match else 0


def runUatu(binary, cnf, timeout, aggressive=False):
	environment = os.environ.copy()
	environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
	environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
	environment["UATU_TIMEOUT_SEC"] = str(timeout)
	environment["UATU_PRINT_MODEL"] = "1"
	if aggressive:
		environment["UATU_REDUCE_INITIAL"] = "4"
		environment["UATU_REDUCE_STEP"] = "4"
		environment["UATU_TIER2_STALE"] = "4"

	return subprocess.run(
		[str(binary), str(cnf)],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		timeout=timeout + 10,
		env=environment,
		check=False,
	)


def validateFormula(binary, path, variables, clauses, expected, aggressive=False):
	result = runUatu(binary, path, 60 if aggressive else 10, aggressive)
	actual = answerFromOutput(result.stdout)
	if actual != expected:
		raise SystemExit(
			f"answer mismatch for {path}: expected={expected}, actual={actual}, "
			f"exit={result.returncode}\n{result.stdout}"
		)
	if actual == "sat" and not verifyModel(
		variables,
		clauses,
		readModel(result.stdout),
	):
		raise SystemExit(f"invalid SAT model for {path}\n{result.stdout}")
	return result.stdout


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

	variables = pigeons * holes
	writeCNF(path, variables, clauses)
	return variables, clauses


def main():
	if len(sys.argv) != 2:
		raise SystemExit(f"usage: {sys.argv[0]} <uatu-binary>")

	binary = Path(sys.argv[1]).resolve()
	work = Path("validation/random")
	work.mkdir(parents=True, exist_ok=True)
	randomGenerator = random.Random(20260831)

	satCases = 0
	unsatCases = 0
	totalCHBUpdates = 0
	totalMinimized = 0
	for index in range(120):
		variables = randomGenerator.randint(4, 10)
		clauseNum = randomGenerator.randint(variables, variables * 6)
		clauses = []
		for _ in range(clauseNum):
			width = randomGenerator.randint(1, min(4, variables))
			selected = randomGenerator.sample(range(1, variables + 1), width)
			clauses.append([
				variable if randomGenerator.getrandbits(1) else -variable
				for variable in selected
			])

		path = work / f"random-{index:03d}.cnf"
		writeCNF(path, variables, clauses)
		expected = solveBruteForce(variables, clauses)
		output = validateFormula(binary, path, variables, clauses, expected)
		totalCHBUpdates += statistic(output, "CHB Score Updates")
		totalMinimized += statistic(output, "Minimized Literals")
		if expected == "sat":
			satCases += 1
		else:
			unsatCases += 1

	pigeonholePath = work / "pigeonhole-7-6.cnf"
	variables, clauses = writePigeonhole(pigeonholePath, 7, 6)
	output = validateFormula(
		binary,
		pigeonholePath,
		variables,
		clauses,
		"unsat",
		True,
	)
	chbUpdates = statistic(output, "CHB Score Updates")
	minimized = statistic(output, "Minimized Literals")
	reductions = statistic(output, "Clause Reductions")
	totalCHBUpdates += chbUpdates
	totalMinimized += minimized

	if chbUpdates == 0:
		raise SystemExit("CHB branching updates were not exercised")
	if minimized == 0:
		raise SystemExit("recursive minimization was not exercised")
	if reductions == 0:
		raise SystemExit("tiered clause reduction was not exercised")

	print(
		f"Validated 120 random CNFs: SAT={satCases}, UNSAT={unsatCases}; "
		f"CHB score updates={totalCHBUpdates}; "
		f"recursive-minimized-literals={totalMinimized}; "
		"pigeonhole tiered reduction=pass"
	)


if __name__ == "__main__":
	main()
