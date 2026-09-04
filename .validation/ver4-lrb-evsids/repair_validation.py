from pathlib import Path


for name in ('validate.py', 'benchmark_validate.py'):
	path = Path('.validation/ver4-lrb-evsids') / name
	path.write_text(path.read_text().replace(') ):', '):'))

path = Path('.validation/ver4-lrb-evsids/validate.py')
text = path.read_text()
old = '''\ttarget = {variable: bool(random.getrandbits(1))
\t          for variable in range(1, variableCount + 1)}
\tclauses = {(-1, 2)}
'''
new = '''\ttarget = {variable: bool(random.getrandbits(1))
\t          for variable in range(1, variableCount + 1)}
\ttarget[1] = False
\tclauses = {(-1, 2)}
'''
if old not in text:
	raise SystemExit('hybrid validation patch point not found')
path.write_text(text.replace(old, new, 1))
