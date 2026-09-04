import csv
import lzma
import os
import subprocess
import sys
import tempfile
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


def variableCount( path ):
	with Path(path).open(errors='replace') as source:
		for line in source:
			stripped = line.strip()
			if stripped.startswith('p '):
				return int(stripped.split()[2])
	raise RuntimeError('missing DIMACS header')


def parseModel( output, expectedVariables ):
	model = None
	for line in output.splitlines():
		fields = line.strip().split()
		if not fields or fields[-1] != '0':
			continue
		try:
			values = [int(field) for field in fields]
		except ValueError:
			continue
		if len(values) == expectedVariables + 1:
			model = values[:-1]
	if model is None:
		raise RuntimeError('SAT result did not contain a complete model')
	return model


def validateModel( model, cnfPath ):
	assignment = {abs(literal): literal > 0 for literal in model}
	clause = []
	with Path(cnfPath).open(errors='replace') as source:
		for line in source:
			stripped = line.strip()
			if not stripped or stripped[0] in 'cp%':
				continue
			for token in stripped.split():
				literal = int(token)
				if literal == 0:
					if not any(
						assignment.get(abs(item), False) == (item > 0)
						for item in clause
					):
						raise RuntimeError('SAT model falsifies the original CNF')
					clause.clear()
				else:
					clause.append(literal)
	if clause:
		raise RuntimeError('unterminated CNF clause')


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
	for marker in (
		'AddressSanitizer',
		'runtime error:',
		'Segmentation fault',
		'Illegal instruction',
		'terminate called',
		'internal error:',
	):
		if marker in output:
			raise RuntimeError(output)
	if completed.returncode not in (0, 10, 20):
		raise RuntimeError(
			f'unexpected exit {completed.returncode}:\n{output}'
		)
	return parseResult(output), output, completed.returncode


def main() ):
	selectedPath, resultPath = sys.argv[1:]
	rows = list(csv.DictReader(Path(selectedPath).open(newline='')))
	if len(rows) != 10:
		raise RuntimeError(f'expected 10 benchmarks, found {len(rows)}')

	results = []
	with tempfile.TemporaryDirectory() as directory:
		root = Path(directory)
		for row in rows:
			archive = root / 'input.cnf.xz'
			cnf = root / 'input.cnf'
			subprocess.run(
				['curl', '-fL', '--retry', '8', '--retry-delay', '5',
				 row['url'], '-o', str(archive)],
				check=True,
			)
			with lzma.open(archive, 'rb') as source, cnf.open('wb') as output:
				while True:
					data = source.read(16 * 1024 * 1024)
					if not data:
						break
					output.write(data)

			variables = variableCount(cnf)
			result, output, releaseExit = runSolver(RELEASE, cnf, 120, True)
			if result == 'error':
				raise RuntimeError(f"benchmark {row['index']} returned no status")
			if result in ('sat', 'unsat') and result != row['expected']:
				raise RuntimeError(
					f"benchmark {row['index']} expected {row['expected']}, got {result}"
				)
			if result == 'sat':
				validateModel(parseModel(output, variables), cnf)

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
			if sanitizeResult == 'error':
				raise RuntimeError(f"sanitizer benchmark {row['index']} returned no status")

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


if __name__ == '__main__':
	main()
