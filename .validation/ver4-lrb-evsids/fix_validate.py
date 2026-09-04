from pathlib import Path


path = Path('.validation/ver4-lrb-evsids/validate.py')
path.write_text(path.read_text().replace(') ):', '):'))
