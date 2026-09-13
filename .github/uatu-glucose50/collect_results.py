#!/usr/bin/env python3
"""Require all fifty frozen instances and audit their answer evidence."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
BASE = '362ceb9ed729c220c7233bd595528248aaddf90a'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sampling = json.loads((HERE / 'sampling.json').read_text())
    sample = json.loads((HERE / 'sample.json').read_text())
    population = json.loads((HERE / 'population.json').read_text())
    manifest = json.loads((HERE / 'expected_source_manifest.json').read_text())
    assert len(population) == 400 and len(sample) == 50
    assert digest(HERE / 'sample.json') == sampling['sample_sha256']
    assert digest(HERE / 'population.json') == sampling['population_sha256']
    assert digest(HERE / 'track_main_2025.uri') == sampling['population_uri_sha256']
    drawn = random.Random(sampling['seed']).sample(population, 50)
    assert [r['hash'] for r in drawn] == [r['hash'] for r in sample]
    assert len({r['hash'] for r in sample}) == 50
    for row, source in zip(sample, drawn):
        assert row['expected'] == source['result'] and row['filename'] == source['filename']
    errors = []
    records = []
    seen = set()
    outcomes = Counter()
    validations = Counter()
    for path in sorted(args.artifacts.rglob('result.json')):
        try:
            record = json.loads(path.read_text())
            index = record['index']
            assert type(index) is int and 0 <= index < 50 and index not in seen
            seen.add(index)
            assert record['benchmark'] == sample[index]
            assert record['sampling'] == sampling
            assert record['solver_base_commit'] == BASE
            assert record['source_manifest'] == manifest
            assert record['source_manifest_sha256'] == canonical(manifest)
            assert record['source_commit'] == os.environ['GITHUB_SHA']
            assert str(record['github_run_id']) == os.environ['GITHUB_RUN_ID']
            assert str(record['github_run_attempt']) == os.environ['GITHUB_RUN_ATTEMPT']
            assert record['checker_sha256'] == digest(HERE / 'validate_model.cpp')
            assert record['evaluator_sha256'] == digest(HERE / 'run_validation.py')
            for name, expected in record.get('artifact_sha256', {}).items():
                assert Path(name).name == name and digest(path.parent / name) == expected
            run = record['uatu']
            assert run['timeout_seconds'] == 1000 and run['memory_limit_bytes'] == 12 * 1024**3
            assert math.isfinite(run['wall_seconds']) and run['wall_seconds'] >= 0
            assert run['log_sha256'] == digest(path.parent / 'uatu.log')
            outcome, validation = run['outcome'], run['validation']
            assert outcome in ('sat', 'unsat', 'timeout', 'resource_limit', 'execution_error')
            good = {'validated_sat_model', 'matches_known_unsat', 'matches_reference_unsat', 'unresolved'}
            bad = {'wrong_result', 'invalid_model', 'execution_error'}
            assert validation in good | bad | {'unverified_unsat'}
            assert record['validation'] == ('complete' if validation in good else
                                            'invalid' if validation in bad else 'unverified')
            if outcome in ('sat', 'unsat'):
                assert run['returncode'] == (10 if outcome == 'sat' else 20)
                assert not run['external_timeout'] and run['wall_seconds'] <= 1000
                if sample[index]['expected'] in ('sat', 'unsat') and validation in good:
                    assert outcome == sample[index]['expected']
            if validation == 'validated_sat_model':
                check = run['model_check']
                assert outcome == 'sat' and check['returncode'] == 0
                assert check['input_sha256'] == record['input']['cnf_sha256']
                assert check['model_sha256'] == digest(path.parent / 'uatu.log')
                assert check['checker_sha256'] == record['checker_sha256']
            if validation == 'matches_known_unsat':
                assert outcome == 'unsat' and sample[index]['expected'] == 'unsat'
            if validation == 'matches_reference_unsat':
                assert outcome == 'unsat' and record['reference']['outcome'] == 'unsat'
                assert record['reference']['returncode'] == 20
                assert record['reference_commit'] == '084d7375975408a06a1397cc4bc645a73b97fa65'
                assert not record['reference']['external_timeout']
                assert record['reference']['wall_seconds'] <= 1000
                assert record['reference']['log_sha256'] == digest(path.parent / 'glucose.log')
            if validation == 'unresolved':
                assert outcome in ('timeout', 'resource_limit')
            outcomes[outcome] += 1
            validations[validation] += 1
            records.append(record)
        except (AssertionError, KeyError, ValueError, OSError) as exc:
            errors.append({'artifact': str(path), 'error': repr(exc)})
    missing = sorted(set(range(50)) - seen)
    failed = sum(validations[k] for k in ('wrong_result', 'invalid_model', 'execution_error'))
    unverified = validations['unverified_unsat']
    summary = {
        'solver_base_commit': BASE, 'source_manifest': manifest, 'sampling': sampling,
        'github_run_id': os.environ['GITHUB_RUN_ID'], 'github_run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
        'experiment_commit': os.environ['GITHUB_SHA'], 'instances': len(records),
        'complete_records': len(records) == 50 and not errors and not missing,
        'outcomes': dict(outcomes), 'validations': dict(validations),
        'detected_wrong_answers_or_execution_errors': failed,
        'unverified_unsat': unverified, 'missing_indices': missing, 'audit_errors': errors,
        'timeout_seconds': 1000, 'memory_limit_bytes': 12 * 1024**3,
        'unsat_check_scope': 'Published GBD status; pinned Glucose corroboration only when GBD status is unknown. No proof certificate checking.',
        'records': sorted(records, key=lambda row: row['index'])
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('records', 'source_manifest')}, indent=2))
    return 0 if summary['complete_records'] and not failed and not unverified else 1


if __name__ == '__main__':
    raise SystemExit(main())
