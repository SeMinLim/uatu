import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import random
import re
import subprocess

SEED = 20260906
PAGE = 'https://benchmark-database.de/?context=cnf&track=main_2025'
URIS = 'https://benchmark-database.de/getinstances?context=cnf&query=track%3Dmain_2025'

class TableReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = []
        self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        elif tag in ('td', 'th'): self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row:
            self.rows.append(self.row)

root = Path('prepared')
root.mkdir(exist_ok=True)
for url, name in [(PAGE, 'source.html'), (URIS, 'track_main_2025.uri')]:
    subprocess.run(['curl', '-fL', '--retry', '4', '--connect-timeout', '30', '--max-time', '180', url, '-o', str(root/name)], check=True)
urls = {}
for line in (root/'track_main_2025.uri').read_text().splitlines():
    match = re.search(r'/file/([0-9a-f]{28,32})(?:\?|/|$)', line)
    if match: urls[match.group(1)] = line.strip()
assert len(urls) == 400, ('official population differs', len(urls))
parser = TableReader()
parser.feed((root/'source.html').read_text())
labels = {}
header = None
for row in parser.rows:
    lower = [cell.lower() for cell in row]
    if 'hash' in lower and 'result' in lower:
        header = lower
    elif header is not None and len(row) == len(header):
        entry = dict(zip(header, row))
        if entry.get('hash') in urls:
            status = entry.get('result', '').lower()
            labels[entry['hash']] = {'expected': status if status in ('sat', 'unsat') else 'unknown', 'filename': entry.get('filename', '')}
assert set(urls) == set(labels), ('missing metadata', len(labels))
selected = random.Random(SEED).sample(sorted(urls), 100)
manifest = [{'index': i, 'hash': digest, 'url': urls[digest], **labels[digest]} for i, digest in enumerate(selected)]
(root/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
selection = {'seed': SEED, 'population': 400, 'selected': 100, 'sampling': 'uniform without replacement; no label, size or runtime filtering', 'manifest_sha256': hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()}
(root/'selection.json').write_text(json.dumps(selection, indent=2)+'\n')
with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
    stream.write('matrix='+json.dumps([{'index': i} for i in range(100)])+'\n')
print(json.dumps(selection))
