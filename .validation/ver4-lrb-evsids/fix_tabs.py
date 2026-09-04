from pathlib import Path


path = Path('cpu/ver_4/branching.cpp')
path.write_text(path.read_text().replace('\\t', '\t'))
