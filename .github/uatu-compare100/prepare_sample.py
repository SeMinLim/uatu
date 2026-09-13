#!/usr/bin/env python3
"""Reproduce the sample from the archived, unfiltered 400-instance population."""
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parent
SEED = 20260913
SAMPLE_COUNT = 100
POPULATION_SHA256 = 'a32bf2d7119955cc7acb67be8b52439f617178d6000f97e824cd41f9feff3b13'
URI_SHA256 = '7c444f6dd65920a8381033d1ba8cc781d796c2c12d4ba7f72b098efdf0f1d8fd'


def main():
    raw_population = (ROOT / 'population.json').read_bytes()
    raw_uri = (ROOT / 'track_main_2025.uri').read_bytes()
    assert hashlib.sha256(raw_population).hexdigest() == POPULATION_SHA256
    assert hashlib.sha256(raw_uri).hexdigest() == URI_SHA256
    population = json.loads(raw_population)
    assert len(population) == 400
    assert population == sorted(population, key=lambda row: row['hash'])
    assert len({row['hash'] for row in population}) == 400
    uri_hashes = sorted(line.strip().rsplit('/', 1)[-1] for line in raw_uri.decode().splitlines() if line.strip())
    assert uri_hashes == [row['hash'] for row in population]
    selected = random.Random(SEED).sample(population, SAMPLE_COUNT)
    sample = [{'index': index, 'hash': row['hash'], 'expected': row['result'],
               'filename': row['filename'], 'family': row['family'],
               'url': 'https://benchmark-database.de/file/' + row['hash'] + '?context=cnf'}
              for index, row in enumerate(selected)]
    sample_bytes = (json.dumps(sample, indent=2) + '\n').encode()
    sampling = {
        'track': 'main_2025', 'population_count': 400, 'sample_count': SAMPLE_COUNT,
        'seed': SEED,
        'method': 'Python random.Random(20260913).sample(population sorted by GBD hash, 100)',
        'filtered_by_size_difficulty_or_result': False,
        'population_source': 'https://benchmark-database.de/getinstances?context=cnf&query=track%3Dmain_2025',
        'metadata_source': 'https://benchmark-database.de/?context=cnf&track=main_2025',
        'official_download_page': 'https://satcompetition.github.io/2025/downloads.html',
        'population_uri_sha256': URI_SHA256,
        'population_sha256': POPULATION_SHA256,
        'sample_sha256': hashlib.sha256(sample_bytes).hexdigest(),
        'sample_hashes_sha256': hashlib.sha256(('\n'.join(row['hash'] for row in sample) + '\n').encode()).hexdigest(),
    }
    (ROOT / 'sample.json').write_bytes(sample_bytes)
    (ROOT / 'sampling.json').write_text(json.dumps(sampling, indent=2) + '\n')
    print(json.dumps(sampling, indent=2))


if __name__ == '__main__':
    main()
