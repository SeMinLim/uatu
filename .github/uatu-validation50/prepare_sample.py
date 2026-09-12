#!/usr/bin/env python3
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import random
import urllib.request

ROOT = Path(__file__).resolve().parent
POPULATION_URL = 'https://benchmark-database.de/getinstances?context=cnf&query=track%3Dmain_2025'
METADATA_URL = 'https://benchmark-database.de/?context=cnf&track=main_2025'
SEED = 20260912

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('td', 'th') and self.row is not None: self.cell = ''
    def handle_data(self, data):
        if self.cell is not None: self.cell += data
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()

def main():
    raw = download(POPULATION_URL)
    html = download(METADATA_URL)
    (ROOT / 'track_main_2025.uri').write_bytes(raw)
    (ROOT / 'metadata.html').write_bytes(html)
    urls = [line.strip() for line in raw.decode().splitlines() if line.strip()]
    hashes = sorted(url.rsplit('/',1)[-1] for url in urls)
    assert len(hashes) == len(set(hashes)) == 400
    parser = TableParser()
    parser.feed(html.decode())
    rows = [row for row in parser.rows if len(row) == 10 and row[0] in hashes]
    assert len(rows) == 400
    headers = ['hash', 'isohash', 'family', 'author', 'result', 'proceedings', 'minisat1m', 'isohash2', 'filename', 'track']
    population = sorted([dict(zip(headers, row)) for row in rows], key=lambda row: row['hash'])
    assert [row['hash'] for row in population] == hashes
    selected = random.Random(SEED).sample(population, 50)
    sample = []
    for index, row in enumerate(selected):
        sample.append({'index':index, 'hash':row['hash'], 'expected':row['result'],
                       'filename':row['filename'], 'family':row['family'],
                       'url':'https://benchmark-database.de/file/' + row['hash'] + '?context=cnf'})
    population_bytes = (json.dumps(population, indent=2) + '\n').encode()
    sample_bytes = (json.dumps(sample, indent=2) + '\n').encode()
    (ROOT / 'population.json').write_bytes(population_bytes)
    (ROOT / 'sample.json').write_bytes(sample_bytes)
    metadata = {
      'track':'main_2025', 'population_count':400, 'sample_count':50, 'seed':SEED,
      'method':'Python random.Random(20260912).sample(population sorted by GBD hash, 50)',
      'filtered_by_size_difficulty_or_result':False,
      'population_source':POPULATION_URL, 'metadata_source':METADATA_URL,
      'official_download_page':'https://satcompetition.github.io/2025/downloads.html',
      'population_uri_sha256':hashlib.sha256(raw).hexdigest(),
      'population_sha256':hashlib.sha256(population_bytes).hexdigest(),
      'sample_sha256':hashlib.sha256(sample_bytes).hexdigest(),
      'sample_hashes_sha256':hashlib.sha256(('\n'.join(row['hash'] for row in sample)+'\n').encode()).hexdigest()
    }
    (ROOT/'sampling.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata,indent=2))
    print('status counts', {key:sum(row['expected']==key for row in sample) for key in ('sat','unsat','unknown')})

if __name__ == '__main__': main()
