#!/usr/bin/env python3
"""Validate all 100 paired runs before reporting a PAR-2 comparison."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys


SAMPLE_COUNT = 100
SAMPLE_SEED = 20260908
TIMEOUT_SECONDS = 1000.0
MEMORY_LIMIT_BYTES = 12 * 1024 ** 3
SOURCE_FILES = ("Makefile", "solver.h", "solver.cpp", "main.cpp")
SOLVERS = ("uatu", "minisat")
OUTCOMES = ("sat", "unsat", "timeout", "resource_limit", "execution_error")
VALIDATIONS = {
    "validated_sat_model", "matches_known_unsat", "matches_other_unsat",
    "unresolved", "wrong_result", "invalid_model", "unverified_unsat",
    "execution_error",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_nonnegative(value):
    return (type(value) in (int, float) and value >= 0
            and (type(value) is int or math.isfinite(value)))


def json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number: " + value)
    return number


def load_json(text):
    return json.loads(text, parse_float=json_float, parse_constant=json_float)


def collect(artifacts, solver_dir, config_dir):
    errors = []
    invalid = False

    def reject(message):
        nonlocal invalid
        invalid = True
        errors.append(message)

    sample = []
    sampling = {}
    manifest = {}
    for name in SOURCE_FILES:
        try:
            manifest[name] = digest(solver_dir / name)
        except OSError as error:
            reject("cannot hash current source %s: %s" % (name, error))
    try:
        sample = load_json((config_dir / "sample.json").read_text())
        if not isinstance(sample, list):
            reject("sample.json must contain a list")
            sample = []
    except (OSError, ValueError) as error:
        reject("cannot read sample.json: %s" % error)
    try:
        sampling = load_json((config_dir / "sampling.json").read_text())
        if not isinstance(sampling, dict):
            reject("sampling.json must contain an object")
            sampling = {}
    except (OSError, ValueError) as error:
        reject("cannot read sampling.json: %s" % error)

    if len(sample) != SAMPLE_COUNT:
        reject("expected 100 sampled instances, got %d" % len(sample))
    if sampling.get("sample_count") != SAMPLE_COUNT:
        reject("sampling.sample_count must be 100")
    if sampling.get("seed") != SAMPLE_SEED:
        reject("sampling.seed must be 20260908")
    if sampling.get("track") != "main_2025":
        reject("sampling.track must be main_2025")
    if sampling.get("sample_sha256"):
        try:
            if sampling["sample_sha256"] != digest(config_dir / "sample.json"):
                reject("sample.json SHA-256 differs from sampling metadata")
        except OSError as error:
            reject("cannot verify sample.json SHA-256: %s" % error)

    expected = {}
    sample_hashes = set()
    for item in sample:
        if not isinstance(item, dict) or type(item.get("index")) is not int:
            reject("sample contains a non-object or a non-integer index")
            continue
        index = item["index"]
        if index in expected:
            reject("duplicate sampled index %d" % index)
        expected[index] = item
        benchmark_hash = item.get("hash")
        if not isinstance(benchmark_hash, str) or not benchmark_hash:
            reject("missing or invalid sampled hash at index %d" % index)
        elif benchmark_hash in sample_hashes:
            reject("duplicate sampled benchmark hash %s" % benchmark_hash)
        else:
            sample_hashes.add(benchmark_hash)

    raw_records = []
    artifact_paths = []
    invalid_artifacts = []
    records = {}
    if not artifacts.is_dir():
        errors.append("artifact directory is missing: %s" % artifacts)
    for path in sorted(artifacts.rglob("result.json")):
        raw = None
        try:
            raw = path.read_text()
            record = load_json(raw)
        except (OSError, UnicodeError, ValueError) as error:
            reject("cannot read artifact %s: %s" % (path, error))
            invalid_artifacts.append({"path": str(path), "error": str(error),
                                      "raw_text": raw})
            continue
        raw_records.append(record)
        artifact_paths.append(str(path))
        if not isinstance(record, dict) or type(record.get("index")) is not int:
            reject("artifact must contain an object with integer index: %s" % path)
            continue
        index = record["index"]
        if index not in expected:
            reject("unexpected result index %d" % index)
            continue
        if index in records:
            reject("duplicate result index %d" % index)
            continue
        records[index] = record

    missing = sorted(set(expected) - set(records))
    if missing:
        errors.append("missing result indices: " + ", ".join(map(str, missing)))
    if len(raw_records) > SAMPLE_COUNT:
        reject("expected exactly 100 result files, got %d" % len(raw_records))

    counts = {solver: Counter({outcome: 0 for outcome in OUTCOMES})
              for solver in SOLVERS}
    validation_counts = {solver: Counter() for solver in SOLVERS}
    penalties = {solver: [] for solver in SOLVERS}
    overlap = {"both_solved": 0, "uatu_only": 0, "minisat_only": 0,
               "neither_solved": 0}

    for index, record in sorted(records.items()):
        item = expected[index]
        if "validation" in record and record["validation"] != "complete":
            reject("record validation is not complete at index %d: %r" %
                   (index, record["validation"]))
        if record.get("benchmark") != item:
            reject("benchmark mismatch at index %d" % index)
        if record.get("sampling") != sampling:
            reject("sampling mismatch at index %d" % index)
        if record.get("source_manifest") != manifest:
            reject("source manifest differs from current solver at index %d" % index)
        pair = {solver: record.get(solver) for solver in SOLVERS}
        if all(isinstance(pair[solver], dict) for solver in SOLVERS):
            answers = {pair[solver].get("outcome") for solver in SOLVERS
                       if isinstance(pair[solver].get("outcome"), str)}
            if answers == {"sat", "unsat"}:
                reject("SAT/UNSAT answer disagreement at index %d" % index)
        solved = {}
        for solver in SOLVERS:
            label = "%s index %d" % (solver, index)
            result = pair[solver]
            solved[solver] = False
            if not isinstance(result, dict):
                reject("missing or invalid solver result: " + label)
                counts[solver]["missing"] += 1
                continue
            outcome = result.get("outcome")
            validation = result.get("validation")
            wall = result.get("wall_seconds")
            if not isinstance(outcome, str) or outcome not in OUTCOMES:
                reject("invalid outcome for %s: %r" % (label, outcome))
                counts[solver]["unknown"] += 1
                continue
            counts[solver][outcome] += 1
            validation_counts[solver][str(validation)] += 1
            if result.get("timeout_seconds") != TIMEOUT_SECONDS:
                reject("timeout must be 1000 seconds for " + label)
            if result.get("memory_limit_bytes") != MEMORY_LIMIT_BYTES:
                reject("memory limit must be 12 GiB for " + label)
            if not finite_nonnegative(wall):
                reject("invalid wall_seconds for " + label)
            if not isinstance(validation, str) or validation not in VALIDATIONS:
                reject("unknown validation for %s: %r" % (label, validation))
            if validation in ("wrong_result", "invalid_model"):
                reject("%s for %s" % (validation, label))
            if outcome == "execution_error":
                reject("execution error for " + label)
                continue
            if outcome in ("timeout", "resource_limit"):
                penalties[solver].append(2 * TIMEOUT_SECONDS)
                continue
            answer_valid = False
            if outcome == "sat":
                answer_valid = validation == "validated_sat_model"
            elif outcome == "unsat":
                if validation == "matches_known_unsat":
                    answer_valid = item.get("expected") == "unsat"
                elif validation == "matches_other_unsat":
                    other = pair["minisat" if solver == "uatu" else "uatu"]
                    answer_valid = (isinstance(other, dict)
                                    and other.get("outcome") == "unsat")
            if item.get("expected") in ("sat", "unsat"):
                if outcome != item["expected"]:
                    reject("answer contradicts known status for " + label)
                    answer_valid = False
            if not answer_valid:
                reject("unvalidated solved answer for %s: %r" % (label, validation))
            time_valid = finite_nonnegative(wall) and wall <= TIMEOUT_SECONDS
            if finite_nonnegative(wall) and wall > TIMEOUT_SECONDS:
                reject("solved answer exceeded 1000-second cutoff for " + label)
            if answer_valid and time_valid:
                solved[solver] = True
                counts[solver]["solved_validated"] += 1
                penalties[solver].append(float(wall))
        if solved["uatu"] and solved["minisat"]:
            overlap["both_solved"] += 1
        elif solved["uatu"]:
            overlap["uatu_only"] += 1
        elif solved["minisat"]:
            overlap["minisat_only"] += 1
        else:
            overlap["neither_solved"] += 1

    complete = (not missing and len(records) == SAMPLE_COUNT
                and len(raw_records) == SAMPLE_COUNT)
    status = "invalid" if invalid else ("complete" if complete else "incomplete")
    scores = None
    if status == "complete":
        scores = {}
        for solver in SOLVERS:
            total = math.fsum(penalties[solver])
            scores[solver] = {"par2_sum_seconds": total,
                              "par2_mean_seconds": total / SAMPLE_COUNT}
        uatu_total = scores["uatu"]["par2_sum_seconds"]
        minisat_total = scores["minisat"]["par2_sum_seconds"]
        scores["ratio_minisat_over_uatu"] = (
            minisat_total / uatu_total if uatu_total else None)
        scores["uatu_outperforms_minisat"] = uatu_total < minisat_total
    for solver in SOLVERS:
        counts[solver].setdefault("solved_validated", 0)
        counts[solver]["executed"] = sum(counts[solver][key] for key in OUTCOMES)

    return {
        "status": status, "errors": errors, "sample_count": len(sample),
        "record_count": len(raw_records), "unique_result_count": len(records),
        "source_manifest": manifest, "sampling": sampling,
        "timeout_seconds": TIMEOUT_SECONDS, "memory_limit_bytes": MEMORY_LIMIT_BYTES,
        "par2_definition": "Mean of validated solve wall time; timeout or resource limit costs 2000 seconds.",
        "counts": counts, "validation_counts": validation_counts,
        "scores": scores, "pair_solved_overlap": overlap,
        "records": raw_records, "artifact_paths": artifact_paths,
        "invalid_artifacts": invalid_artifacts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--solver-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = collect(args.artifacts, args.solver_dir, Path(__file__).resolve().parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: summary[key] for key in
                      ("status", "sample_count", "record_count", "counts", "scores", "errors")},
                     indent=2))
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
