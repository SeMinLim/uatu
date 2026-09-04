import csv
import itertools
import lzma
import os
import random
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


RELEASE = 'cpu/ver_4/obj/uatu_solver'
SANITIZER = 'cpu/ver_4/obj/uatu_solver_sanitize'


def parseResult( output ):
	lines = {line.strip() for line in output.splitlines()}
	if 'UNSATISFIABLE' in lines:
		return 'unsat'
	if 'SATISFIABLE' in lines:
		return 'sat'
	if 'UNSOLVED' in lines:
		return 'unsolved'
	return 'error'


def parseStat( output, name ):
	for line in output.splitlines():
		if not line.startswith(name):
			continue
		return int(line.split(':', 1)[1].strip())
	return 0


def parseModel( output, variableCount ):
	model = None
	for line in output.splitlines():
		fields = line.strip().split()
		if not fields or fields[-1] != '0':
			continue
		try:
			values = [int(field) for field in fields]
		except ValueError:
			continue
		if len(values) == variableCount + 1:
			model = values[:-1]
	if model is None:
		raise RuntimeError('SAT result did not contain a complete model')
	return model


def validateModel( model, clauses ):
	assignment = {abs(literal): literal > 0 for literal in model}
	for clause in clauses:
		if not any(assignment.get(abs(literal), False) == (literal > 0)
		           for literal in clause):
			raise RuntimeError('SAT model falsifies a clause')


def readCNF( path ):
	variableCount = 0
	clauses = []
	clause = []
	with Path(path).open(errors='replace') as source:
		for line in source:
			stripped = line.strip()
			if not stripped or stripped[0] in 'c%':
				continue
			if stripped.startswith('p '):
				variableCount = int(stripped.split()[2])
				continue
			for token in stripped.split():
				literal = int(token)
				if literal == 0:
					clauses.append(clause)
					clause = []
				else:
					clause.append(literal)
	if clause:
		raise RuntimeError('unterminated CNF clause')
	return variableCount, clauses


def writeCNF( path, variableCount, clauses ):
	with Path(path).open('w') as output:
		output.write(f'p cnf {variableCount} {len(clauses)}\n')
		for clause in clauses:
			output.write(' '.join(map(str, clause)) + ' 0\n')


def runSolver( binary, path, timeoutSec, printModel, extraEnvironment=None ):
	environment = os.environ.copy()
	environment['UATU_TIMEOUT_SEC'] = str(timeoutSec)
	if printModel:
		environment['UATU_PRINT_MODEL'] = '1'
	if extraEnvironment:
		environment.update(extraEnvironment)
	try:
		completed = subprocess.run(
			[binary, str(path)],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=timeoutSec + 15,
			env=environment,
			check=False,
		)
	except subprocess.TimeoutExpired as error:
		output = error.stdout or ''
		if isinstance(output, bytes):
			output = output.decode(errors='replace')
		return 'unsolved', output, 124

	output = completed.stdout
	if 'AddressSanitizer' in output or 'runtime error:' in output:
		raise RuntimeError(output)
	if 'Segmentation fault' in output or 'Illegal instruction' in output:
		raise RuntimeError(output)
	if 'terminate called' in output or 'internal error:' in output:
		raise RuntimeError(output)
	if completed.returncode not in (0, 10, 20):
		raise RuntimeError(
			f'unexpected exit {completed.returncode}:\n{output}'
		)
	return parseResult(output), output, completed.returncode


def bruteForce( variableCount, clauses ):
	for values in itertools.product((False, True), repeat=variableCount):
		if all(any(values[abs(literal) - 1] == (literal > 0)
		           for literal in clause) for clause in clauses):
			return 'sat'
	return 'unsat'


def validateRandomCNFs() ):
	pass


def randomValidation() ):
	random.seed(20260904)
	with tempfile.TemporaryDirectory() as directory:
		root = Path(directory)
		for trial in range(500):
			variableCount = random.randint(1, 8)
			clauseCount = random.randint(1, 30)
			clauses = []
			for _ in range(clauseCount):
				length = random.randint(1, min(variableCount, 6))
				variables = random.sample(range(1, variableCount + 1), length)
				clauses.append([
					variable if random.getrandbits(1) else -variable
					for variable in variables
				])
			path = root / f'random-{trial}.cnf'
			writeCNF(path, variableCount, clauses)
			expected = bruteForce(variableCount, clauses)
			result, output, _ = runSolver(RELEASE, path, 10, True)
			if result != expected:
				raise RuntimeError(
					f'release mismatch {trial}: expected {expected}, got {result}'
				)
			if result == 'sat':
				validateModel(parseModel(output, variableCount), clauses)

			if trial < 150:
				result, output, _ = runSolver(
					SANITIZER,
					path,
					10,
					True,
					{
						'ASAN_OPTIONS': 'detect_leaks=0:halt_on_error=1:abort_on_error=1',
						'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1',
					},
				)
				if result != expected:
					raise RuntimeError(
						f'sanitizer mismatch {trial}: expected {expected}, got {result}'
					)
	print('validated 500 release and 150 sanitizer random CNFs')


def hybridValidation() ):
	random.seed(701)
	variableCount = 100
	target = {variable: bool(random.getrandbits(1))
	          for variable in range(1, variableCount + 1)}
	clauses = {(-1, 2)}
	while len(clauses) < 1200:
		variables = random.sample(range(1, variableCount + 1), 3)
		clause = []
		for variable in variables:
			literal = variable if random.getrandbits(1) else -variable
			clause.append(literal)
		if not any(target[abs(literal)] == (literal > 0) for literal in clause):
			variable = abs(clause[0])
			clause[0] = variable if target[variable] else -variable
		clauses.add(tuple(clause))

	path = Path('/tmp/hybrid.cnf')
	writeCNF(path, variableCount, list(clauses))
	result, output, _ = runSolver(
		RELEASE,
		path,
		60,
		True,
		{'UATU_BRANCH_PHASE_PROPAGATIONS': '1'},
	)
	if result != 'sat':
		raise RuntimeError('hybrid-path CNF was not solved as SAT')
	validateModel(parseModel(output, variableCount), list(clauses))

	lrbDecisions = parseStat(output, 'LRB Decisions')
	evsidsDecisions = parseStat(output, 'EVSIDS Decisions')
	switches = parseStat(output, 'Branching Switches')
	updates = parseStat(output, 'LRB Updates')
	if min(lrbDecisions, evsidsDecisions, switches, updates) <= 0:
		raise RuntimeError(
			f'incomplete hybrid path: LRB={lrbDecisions}, EVSIDS={evsidsDecisions}, '
			f'switches={switches}, updates={updates}'
		)
	print(
		f'hybrid path: LRB={lrbDecisions}, EVSIDS={evsidsDecisions}, '
		f'switches={switches}, updates={updates}'
	)


def selectBenchmarks( sourcePath, selectedPath ):
	rows = list(csv.DictReader(Path(sourcePath).open(newline='')))
	sat = [row for row in rows if row['expected'] == 'sat']
	unsat = [row for row in rows if row['expected'] == 'unsat']
	random.seed(20260904)
	selected = random.sample(sat, 5) + random.sample(unsat, 5)
	random.shuffle(selected)
	with Path(selectedPath).open('w', newline='') as output:
		writer = csv.DictWriter(
			output,
			fieldnames=['index', 'expected', 'hash', 'url'],
		)
		writer.writeheader()
		for index, row in enumerate(selected):
			writer.writerow({
				'index': index,
				'expected': row['expected'],
				'hash': row['hash'],
				'url': row['url'],
			})


def benchmarkValidation( selectedPath, resultPath ):
	rows = list(csv.DictReader(Path(selectedPath).open(newline='')))
	results = []
	with tempfile.TemporaryDirectory() as directory:
		root = Path(directory)
		for row in rows:
			archive = root / 'input.cnf.xz'
			cnf = root / 'input.cnf'
			urllib.request.urlretrieve(row['url'], archive)
			with lzma.open(archive, 'rb') as source, cnf.open('wb') as output:
				while True:
					data = source.read(16 * 1024 * 1024)
					if not data:
						break
					output.write(data)

			variableCount, clauses = readCNF(cnf)
			result, output, releaseExit = runSolver(RELEASE, cnf, 120, True)
			if result in ('sat', 'unsat') and result != row['expected']:
				raise RuntimeError(
					f"benchmark {row['index']} expected {row['expected']}, got {result}"
				)
			if result == 'sat':
				validateModel(parseModel(output, variableCount), clauses)

			sanitizeResult, _, sanitizeExit = runSolver(
				SANITIZER,
				cnf,
				20,
				False,
				{
					'ASAN_OPTIONS': 'detect_leaks=0:halt_on_error=1:abort_on_error=1',
					'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1',
				},
			)
			results.append({
				'index': row['index'],
				'expected': row['expected'],
				'hash': row['hash'],
				'release_result': result,
				'release_exit': releaseExit,
				'sanitizer_result': sanitizeResult,
				'sanitizer_exit': sanitizeExit,
				'status': 'clean',
			})
			archive.unlink(missing_ok=True)
			cnf.unlink(missing_ok=True)

	with Path(resultPath).open('w', newline='') as output:
		writer = csv.DictWriter(output, fieldnames=list(results[0]))
		writer.writeheader()
		writer.writerows(results)
	print(f'validated {len(results)} SAT Competition 2025 benchmarks')


def main() ):
	if len(sys.argv) < 2:
		raise SystemExit('usage: validate.py core|select|benchmarks ...')
	if sys.argv[1] == 'core':
		randomValidation()
		hybridValidation()
	elif sys.argv[1] == 'select':
		selectBenchmarks(sys.argv[2], sys.argv[3])
	elif sys.argv[1] == 'benchmarks':
		benchmarkValidation(sys.argv[2], sys.argv[3])
	else:
		raise SystemExit('unknown validation mode')


if __name__ == '__main__':
	main()
