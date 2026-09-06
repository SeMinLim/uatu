from pathlib import Path
import shutil

root = Path('cpu/ver_5')
p = root/'solver.cpp'
s = p.read_text()
s = s.replace('clauseDB[learnedClause].activity = clause_inc;', 'clauseDB[learnedClause].activity = heuristics.lbdReduction ? clause_inc : 0.0;')
p.write_text(s)
p = root/'tests/regression.py'
s = p.read_text()
old = '\t\ts.vars = 2;\n\t\ts.initialize();\n\t\tstd::vector<int> a{1, 2};\n\t\tstd::vector<int> b{-1, 2};'
new = '\t\ts.vars = 3;\n\t\ts.initialize();\n\t\tstd::vector<int> a{1, 2, 3};\n\t\tstd::vector<int> b{-1, 2, 3};'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
shutil.copyfile('validation_temp/heuristics_regression.py', root/'tests/heuristics_regression.py')
