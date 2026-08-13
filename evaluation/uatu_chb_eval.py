#!/usr/bin/env python3

import argparse
import csv
import hashlib
import itertools
import json
import os
import random
import shlex
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path


SEED = "uatu-v3-chb-satcomp2025-subset-v1"
TIMEOUT_SEC = 1000
SOLVERS = ("minisat", "v3", "chb")


def runCommand(command, **kwargs):
	print( "+ " + " ".join(shlex.quote(str(item)) for item in command), flush=True )
	return subprocess.run(command, check=True, **kwargs)


def readURLs(path):
	return sorted({
		line.strip()
		for line in Path(path).read_text().splitlines()
		if line.strip().startswith("http")
	})


def selectURLs(urls, count, label):
	ranked = sorted(
		urls,
		key=lambda url: hashlib.sha256(
			f"{SEED}:{label}:{url}".encode()
		).hexdigest(),
	)
	if len(ranked) < count:
		raise RuntimeError(f"not enough {label} instances: {len(ranked)}")
	return ranked[:count]


def prepareSubset(outputPath, githubOutput):
	runCommand([
		"curl", "-fsSL",
		"https://benchmark-database.de/getinstances?context=cnf&query=result%3Dsat%20and%20track%3Dmain_2025",
		"-o", "sat.uri",
	])
	runCommand([
		"curl", "-fsSL",
		"https://benchmark-database.de/getinstances?context=cnf&query=result%3Dunsat%20and%20track%3Dmain_2025",
		"-o", "unsat.uri",
	])

	selected = [("sat", url) for url in selectURLs(readURLs("sat.uri"), 50, "sat")]
	selected += [("unsat", url) for url in selectURLs(readURLs("unsat.uri"), 50, "unsat")]
	selected.sort(
		key=lambda item: hashlib.sha256(
			f"{SEED}:order:{item[0]}:{item[1]}".encode()
		).hexdigest()
	)

	with Path(outputPath).open("w", newline="") as output:
		writer = csv.writer(output)
		writer.writerow(["index", "expected", "url"])
		for index, (expected, url) in enumerate(selected):
			writer.writerow([index, expected, url])

	with Path(githubOutput).open("a") as output:
		output.write("indices=" + json.dumps(list(range(100)), separators=(",", ":")) + "\n")


def patchCHB(sourceDir, outputDir):
	runCommand([
		"python3", "evaluation/uatu_major_patch.py",
		str(sourceDir), str(outputDir),
	])
	path = Path(outputDir) / "solver.cpp"
	text = path.read_text()
	old = "else chbLastConflict[variable] = conflicts;"
	new = "else chbLastConflict[variable] = conflicts + 1;"
	if old not in text:
		raise RuntimeError("CHB conflict-age patch point not found")
	path.write_text(text.replace(old, new, 1))


def buildSolvers():
	runCommand(["make", "-C", "cpu/ver_3", "clean", "all"])
	patchCHB("cpu/ver_3", "work/chb")
	runCommand(["make", "-C", "work/chb", "clean", "all"])


def expectedResult(variableCount, clauses):
	for assignment in itertools.product((False, True), repeat=variableCount):
		if all(
			any(assignment[abs(literal) - 1] == (literal > 0) for literal in clause)
			for clause in clauses
		):
			return "SATISFIABLE"
	return "UNSATISFIABLE"


def solverResult(binary, path, env=None):
	completed = subprocess.run(
		[binary, str(path)],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		timeout=10,
		check=False,
		env=env,
	)
	lines = {line.strip() for line in completed.stdout.splitlines()}
	if "UNSATISFIABLE" in lines:
		return "UNSATISFIABLE"
	if "SATISFIABLE" in lines:
		return "SATISFIABLE"
	raise RuntimeError(f"{binary} returned no result:\n{completed.stdout}")


def validateSolvers():
	buildSolvers()
	random.seed(20250813)
	with tempfile.TemporaryDirectory() as directory:
		root = Path(directory)
		for trial in range(500):
			variableCount = random.randint(1, 8)
			clauseCount = random.randint(1, 24)
			clauses = []
			for _ in range(clauseCount):
				length = random.randint(1, min(variableCount, 5))
				variables = random.sample(range(1, variableCount + 1), length)
				clauses.append([
					variable if random.getrandbits(1) else -variable
					for variable in variables
				])
			path = root / f"test-{trial}.cnf"
			with path.open("w") as output:
				output.write(f"p cnf {variableCount} {len(clauses))}\n")
				for clause in clauses:
					output.write(" ".join(map(str, clause)) + " 0\n)"
			expected = expectedResult(variableCount, clauses)
			results = (
				solverResult("cpu/ver_3/obj/uatu_solver", path),
				solverResult(
					"work/chb/obj/uatu_solver",
					path,
					env={**os.environ, "UATU_BRANCHING": "chb"},
				),
			)
			if results != (expected, expected):
				raise RuntimeError(
					f"mismatch trial={trial} expected={expected} results={results}"
				)
	print( "Validated 500 random CNFs." )


def readSelectedRow(manifestPath, index):
	with Path(manifestPath).open(newline="") as source:
		rows = list(csv.DictReader(source))
	if index < 0 or index >= len(rows):
		raise RuntimeError(f"invalid subset index: {index}")
	return rows[index]


def downloadInstance(url, outputPath):
	outputPath = Path(outputPath)
	outputPath.parent.mkdir(parents=True, exist_ok=True)
	compressed = outputPath.with_suffix(outputPath.suffix + ".xz")
	runCommand([
		"curl", "-fL", "--retry", "8", "--retry-delay", "5",
		url, "-o", str(compressed),
	])
	runCommand(["xz", "-t", str(compressed)])
	with outputPath.open("wb") as output:
		runCommand(["xz", "-dc", str(compressed)], stdout=output)


def parseAnswer(output, returnCode):
	lines = {line.strip() for line in output.splitlines()}
	if "UNSATISFIABLE" in lines:
		return "unsat"
	if "SATISFIABLE" in lines:
		return "sat"
	if returnCode in (124, 137, 143) or "UNSOLVED" in lines:
		return "timeout"
	return "error"


def readUatuModel(output):
	for line in output.splitlines():
		fields = line.split()
		if not fields or fields[-1] != "0":
			continue
		try:
			values = [int(token) for token in fields]
		except ValueError:
			continue
		if len(values) > 2:
			return values[:-1]
	return []


def readMiniSATModel(path):
	try:
		lines = Path(path).read_text(errors="ignore").splitlines()
	except FileNotFoundError:
		return []
	model = []
	for line in lines[1:]:
		for token in line.split():
			value = int(token)
			if value != 0:
				model.append(value)
	return model


def verifyModel(model, cnfPath):
	assignment = {abs(literal): literal > 0 for literal in model if literal != 0}
	if not assignment:
		return False

	clause = []
	with Path(cnfPath).open(errors="ignore") as source:
		for line in source:
			stripped = line.lstrip()
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


def runTimed(command, outputPath, timePath):
	with Path(outputPath).open("w") as output:
		completed = subprocess.run(
			[
				"/usr/bin/time", "-q", "-f", "%e,%U,%S,%M", "-o", str(timePath),
				"timeout", "--signal=TERM", "--kill-after=5s", f"{TIMEOUT_SEC}s",
				"bash", "-lc", command,
			],
			stdout=output,
			stderr=subprocess.STDOUT,
			check=False,
		)
	return completed.returncode


def runSolver(index, expected, url, solver, cnfPath, outputDir):
	outputDir = Path(outputDir)
	outputDir.mkdir(parents=True, exist_ok=True)
	outputPath = outputDir / f"{solver}.out"
	timePath = outputDir / f"{solver}.time"
	modelPath = outputDir / f"{solver}.model"

	if solver == "minisat":
		command = (
			f"minisat -verb=0 -cpu-lim={TIMEOUT_SEC} "
			f"{shlex.quote(str(cnfPath))} {shlex.quote(str(modelPath))}"
		)
	elif solver == "v3":
		command = (
			f"UATU_TIMEOUT_SEC={TIMEOUT_SEC} UATU_PRINT_MODEL=1 "
			f"cpu/ver_3/obj/uatu_solver {shlex.quote(str(cnfPath))}"
		)
	elif solver == "chb":
		command = (
			f"UATU_TIMEOUT_SEC={TIMEOUT_SEC} UATU_PRINT_MODEL=1 "
			f"UATU_BRANCHING=chb work/chb/obj/uatu_solver {shlex.quote(str(cnfPath))}"
		)
	else:
		raise RuntimeError(f"unknown solver: {solver}")

	returnCode = runTimed(command, outputPath, timePath)
	output = outputPath.read_text(errors="ignore")
	answer = parseAnswer(output, returnCode)
	modelValid = 1
	if answer == "sat":
		model = readMiniSATModel(modelPath) if solver == "minisat" else readUatuModel(output)
		modelValid = int(verifyModel(model, cnfPath))
	correct = int(answer == expected and modelValid == 1)

	wall = float(TIMEOUT_SEC)
	user = 0.0
	system = 0.0
	rss = 0
	if timePath.exists() and timePath.stat().st_size > 0:
		fields = timePath.read_text().strip().split(",")
		if len(fields) == 4:
			wall = float(fields[0])
			user = float(fields[1])
			system = float(fields[2])
			rss = int(float(fields[3]))

	return {
		"index": index,
		"expected": expected,
		"solver": solver,
		"result": answer,
		"correct": correct,
		"model_valid": modelValid,
		"wall_sec": wall,
		"user_sec": user,
		"sys_sec": system,
		"rss_kb": rss,
		"exit_code": returnCode,
		"url": url,
	}


def evaluateInstance(manifestPath, index, outputPath):
	buildSolvers()
	row = readSelectedRow(manifestPath, index)
	instancePath = Path("work/instance/input.cnf")
	downloadInstance(row["url"], instancePath)

	order = list(SOLVERS[index % len(SOLVERS):] + SOLVERS[:index % len(SOLVERS)])
	results = []
	for solver in order:
		results.append(runSolver(
			index,
			row["expected"],
			row["url"],
			solver,
			instancePath,
			"work/results",
		))
	results.sort(key=lambda result: SOLVERS.index(result["solver"]))

	fields = list(results[0])
	Path(outputPath).parent.mkdir(parents=True, exist_ok=True)
	with Path(outputPath).open("w", newline="") as output:
		writer = csv.DictWriter(output, fieldnames=fields)
		writer.writeheader()
		writer.writerows(results)


def aggregateResults(downloadDir, manifestPath, outputDir):
	rows = []
	for path in Path(downloadDir).glob("uatu-chb-result-*/results.csv"):
		with path.open(newline="") as source:
			rows.extend(csv.DictReader(source))
	if len(rows) != 300:
		raise RuntimeError(f"expected 300 rows, found {len(rows)}")

	rows.sort(key=lambda row: (row["solver"], int(row["index"])))
	outputDir = Path(outputDir)
	outputDir.mkdir(parents=True, exist_ok=True)
	Path(manifestPath).replace(outputDir / "subset100.csv")

	with (outputDir / "raw_results.csv").open("w", newline="") as output:
		writer = csv.DictWriter(output, fieldnames=list(rows[0]))
		writer.writeheader()
		writer.writerows(rows)

	summary = []
	for solver in SOLVERS:
		selected = [row for row in rows if row["solver"] == solver]
		solved = [row for row in selected if row["correct"] == "1"]
		wrong = [
			row for row in selected
			if row["result"] in ("sat", "unsat") and row["correct"] != "1"
		]
		satSolved = sum(
			row["expected"] == "sat" and row["correct"] == "1"
			for row in selected
		)
		unsatSolved = sum(
			row["expected"] == "unsat" and row["correct"] == "1"
			for row in selected
		)
		par2 = sum(
			min(float(row["wall_sec"]), TIMEOUT_SEC)
			if row["correct"] == "1"
			else 2.0 * TIMEOUT_SEC
			for row in selected
		) / len(selected)
		solvedTimes = [float(row["wall_sec"]) for row in solved]
		summary.append({
			"solver": solver,
			"solved": len(solved),
			"sat_solved": satSolved,
			"unsat_solved": unsatSolved,
			"par2_sec": par2,
			"sum_solved_sec": sum(solvedTimes),
			"median_solved_sec": statistics.median(solvedTimes) if solvedTimes else 0.0,
			"peak_rss_kb": max((int(float(row["rss_kb"])) for row in selected), default=0),
			"wrong_answers": len(wrong),
		})

	summary.sort(key=lambda row: (-row["solved"], row["par2_sec"], row["sum_solved_sec"]))
	for rank, row in enumerate(summary, 1):
		row["rank"] = rank

	fields = [
		"rank", "solver", "solved", "sat_solved", "unsat_solved",
		"par2_sec", "sum_solved_sec", "median_solved_sec",
		"peak_rss_kb", "wrong_answers",
	]
	with (outputDir / "summary.csv").open("w", newline="") as output:
		writer = csv.DictWriter(output, fieldnames=fields)
		writer.writeheader()
		writer.writerows(summary)

	bySolver = {row["solver"]: row for row in summary}
	chb = bySolver["chb"]
	v3 = bySolver["v3"]
	minisat = bySolver["minisat"]

	def beats(candidate, baseline):
		return candidate["wrong_answers"] == 0 and (
			candidate["solved"] > baseline["solved"] or
			(
				candidate["solved"] == baseline["solved"] and
				candidate["par2_sec"] < baseline["par2_sec"]
			)
		)

	chbBeatsV3 = beats(chb, v3)
	chbBeatsMiniSAT = beats(chb, minisat)

	lines = [
		"# Uatu V3 + CHB Evaluation",
		"",
		"- Suite: deterministic 100-instance SAT Competition 2025 Main subset",
		"- Composition: 50 SAT and 50 UNSAT instances",
		"- Selection: SHA-256 ranking with fixed seed; no MiniSAT runtime metadata used",
		"- Timeout: 1,000 seconds per solver and instance",
		"- PAR-2 penalty: 2,000 seconds for timeout, error, or wrong answer",
		"",
		"| Rank | Solver | Solved | SAT | UNSAT | PAR-2 (s) | Sum solved time (s) | Median solved time (s) | Peak RSS (KB) | Wrong |",
		"|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
	]
	for row in summary:
		lines.append(
			f"| {row['rank']} | {row['solver']} | {row['solved']} | "
			f"{row['sat_solved']} | {row['unsat_solved']} | "
			f"{row['par2_sec']:.3f} | {row['sum_solved_sec']:.3f} | "
			f"{row['median_solved_sec']:.3f} | {row['peak_rss_kb']} | "
			f"{row['wrong_answers']} |"
		)
	lines += [
		"",
		f"- CHB beats V3: **{'yes' if chbBeatsV3 else 'no'}**",
		f"- CHB beats MiniSAT: **{'yes' if chbBeatsMiniSAT else 'no'}**",
	]
	(outputDir / "REPORT.md").write_text("\n".join(lines) + "\n")
	(outputDir / "decision.json").write_text(json.dumps({
		"chb_beats_v3": chbBeatsV3,
		"chb_beats_minisat": chbBeatsMiniSAT,
		"summary": summary,
	}, indent=2) + "\n")
	print( (outputDir / "REPORT.md").read_text() )


def main():
	parser = argparse.ArgumentParser()
	subparsers = parser.add_subparsers(dest="command", required=True)

	prepare = subparsers.add_parser("prepare")
	prepare.add_argument("output")
	prepare.add_argument("github_output")

	subparsers.add_parser("validate")

	evaluate = subparsers.add_parser("evaluate")
	evaluate.add_argument("manifest")
	evaluate.add_argument("index", type=int)
	evaluate.add_argument("output")

	aggregate = subparsers.add_parser("aggregate")
	aggregate.add_argument("download_dir")
	aggregate.add_argument("manifest")
	aggregate.add_argument("output_dir")

	args = parser.parse_args()
	if args.command == "prepare":
		prepareSubset(args.output, args.github_output)
	elif args.command == "validate":
		validateSolvers()
	elif args.command == "evaluate":
		evaluateInstance(args.manifest, args.index, args.output)
	elif args.command == "aggregate":
		aggregateResults(args.download_dir, args.manifest, args.output_dir)


if __name__ == "__main__":
	main()
