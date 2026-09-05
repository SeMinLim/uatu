import hashlib
import json
import os
import random
import re
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

SEED = 20260905
PAGE = 'https://benchmark-database.de/?context=cnf&track=main_2025'
URIS = 'https://benchmark-database.de/getinstances?context=cnf&query=track%3Dmain_2025'

class TableReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row:
            self.rows.append(self.row)
            self.row = []

def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Uatu-sanity-evaluation/1.0'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()

root = Path('prepared')
root.mkdir(exist_ok=True)
html = get(PAGE)
uri_bytes = get(URIS)
(root / 'source.html').write_bytes(html)
(root / 'track_main_2025.uri').write_bytes(uri_bytes)
urls = {}
for line in uri_bytes.decode('utf-8').splitlines():
    url = line.strip()
    match = re.search(r'/file/([0-9a-f]{28,32})(?:[?/] |[?]|/|$)', url)
    if match:
        urls[match.group(1)] = url
if len(urls) != 400:
    raise RuntimeError(f'Expected 400 unique official Main Track instances; found {len(urls)}')
parser = TableReader()
parser.feed(html.decode('utf-8'))
labels = {}
header = None
for row in parser.rows:
    lowered = [cell.lower() for cell in row]
    if 'hash' in lowered and 'result' in lowered:
        header = lowered
        continue
    if header is None or len(row) != len(header):
        continue
    entry = dict(zip(header, row))
    digest = entry.get('hash', '')
    if digest in urls:
        result = entry.get('result', 'unknown').lower()
        labels[digest] = {'expected': result if result in ('sat', 'unsat') else 'unknown',
                          'filename': entry.get('filename', ''), 'family': entry.get('family', '')}
if set(labels) != set(urls):
    raise RuntimeError(f'Metadata coverage is {len(labels)}/400; refusing to filter or silently substitute instances')
chosen = random.Random(SEED).sample(sorted(urls), 100)
manifest = []
for index, digest in enumerate(chosen):
    manifest.append({'index': index, 'hash': digest, 'url': urls[digest], **labels[digest]})
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
selection = {'seed': SEED, 'population': 400, 'selected': 100,
             'sampling': 'uniform without replacement; no size, label, or runtime filter',
             'labels': dict(Counter(row['expected'] for row in manifest)),
             'manifest_sha256': hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()}
(root / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n')
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write('matrix=' + json.dumps([{'index': row['index']} for row in manifest]) + '\n')
print(json.dumps(selection, indent=2))
