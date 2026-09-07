#!/usr/bin/env python3
"""Require all 50 instance records and the exact candidate source manifest."""
import argparse
import base64
import collections
import hashlib
import json
from pathlib import Path
import sys
import zlib


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--solver-dir',type=Path,required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    sample = json.loads((here/'sample.json').read_text())
    sampling = json.loads((here/'sampling.json').read_text())
    manifest = {name:digest(args.solver_dir/name) for name in ('Makefile','solver.h','solver.cpp','main.cpp')}
    records = {}
    errors = []
    for path in sorted(args.artifacts.rglob('result.json')):
        record = json.loads(path.read_text())
        index = record.get('index')
        if index in records:
            errors.append('duplicate index '+str(index))
        records[index] = record
    for item in sample:
        index = item['index']
        if index not in records:
            errors.append('missing index '+str(index))
            continue
        row = records[index]
        if row.get('benchmark') != item:
            errors.append('benchmark mismatch '+str(index))
        if row.get('sampling') != sampling:
            errors.append('sampling mismatch '+str(index))
        if row.get('source_manifest') != manifest:
            errors.append('source mismatch '+str(index))
        good = ('validated_sat_model','matches_known_unsat','matches_minisat_unsat','unresolved')
        if row.get('validation') not in good:
            errors.append('validation '+str(index)+': '+str(row.get('validation')))
        if row.get('uatu',{}).get('timeout_seconds') != 1000.0:
            errors.append('timeout mismatch '+str(index))
    if len(records) != 50:
        errors.append('expected 50 results, got '+str(len(records)))
    ordered = [records[index] for index in sorted(records)]
    outcomes = collections.Counter(row.get('uatu',{}).get('outcome','missing') for row in ordered)
    validations = collections.Counter(row.get('validation','missing') for row in ordered)
    summary = {
        'status':'complete' if not errors else 'incomplete_or_failed',
        'sampling':sampling, 'sample':sample, 'source_manifest':manifest,
        'timeout_seconds':1000, 'memory_limit_bytes':12*1024**3,
        'timing':'external wall clock from process launch, includes parsing and model output',
        'sat_validation':'every emitted SAT model checked against all original CNF clauses',
        'unsat_validation':'known GBD status; unknown UNSAT requires independent MiniSAT agreement',
        'unsat_proof_checking':False,
        'counts':{'requested':50,'executed':len(records),'outcomes':dict(outcomes),'validation':dict(validations)},
        'errors':errors, 'records':ordered
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({'status':summary['status'],'counts':summary['counts'],'errors':errors},indent=2))
    raw = args.output.read_bytes()
    encoded = base64.b64encode(zlib.compress(raw,9)).decode()
    print('UATU_SUMMARY_SHA256=' + hashlib.sha256(raw).hexdigest())
    for index, offset in enumerate(range(0,len(encoded),16000)):
        print('UATU_SUMMARY_ZLIB_BASE64_%03d=' % index + encoded[offset:offset+16000])
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
