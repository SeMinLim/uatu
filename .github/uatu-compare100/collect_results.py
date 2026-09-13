#!/usr/bin/env python3
"""Audit all 100 paired SAT 2025 runs before publishing a PAR-2 comparison."""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sys


SAMPLE_COUNT = 100
POPULATION_COUNT = 400
SAMPLE_SEED = 20260913
TIMEOUT_SECONDS = 1000.0
MEMORY_LIMIT_BYTES = 12 * 1024 ** 3
UATU_BASE_COMMIT = "a4dc75bc104c84762193446fc2ae15c58fb97908"
MINISAT_COMMIT = "eb01ad68b75bb3b34ff8657c37ad6a31faae0fc3"
SOLVERS = ("uatu", "minisat")
OUTCOMES = ("sat", "unsat", "timeout", "resource_limit", "execution_error")
GOOD_VALIDATIONS = {"validated_sat_model", "matches_known_unsat", "matches_other_unsat", "unresolved"}
VALIDATIONS = GOOD_VALIDATIONS | {"wrong_result", "invalid_model", "unverified_unsat", "execution_error"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
GBD_HASH = re.compile(r"[0-9a-f]{28,32}\Z")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def valid_digest(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def finite_nonnegative(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def json_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number: " + value)
    return number


def load_json(text):
    return json.loads(text, parse_float=json_number, parse_constant=json_number,
                      object_pairs_hook=strict_pairs)


def source_manifest(solver_dir):
    paths = {path.relative_to(solver_dir).as_posix(): path
             for path in solver_dir.rglob("*")
             if path.is_file() and (path.suffix in (".h", ".cpp") or path.name == "Makefile")}
    return {name: digest(path) for name, path in sorted(paths.items())}


def collect(artifacts, solver_dir, config_dir, expected_source_commit=None,
            expected_run_id=None, expected_run_attempt=None):
    errors = []
    invalid = False
    unverified = False

    def reject(message):
        nonlocal invalid
        invalid = True
        errors.append(message)

    def read_config(name, kind, default):
        try:
            data = load_json((config_dir / name).read_text())
            if not isinstance(data, kind):
                raise ValueError("unexpected JSON type")
            return data
        except (OSError, UnicodeError, ValueError) as error:
            reject("cannot read %s: %s" % (name, error))
            return default

    expected_source_commit = expected_source_commit or os.environ.get("GITHUB_SHA")
    expected_run_id = expected_run_id or os.environ.get("GITHUB_RUN_ID")
    expected_run_attempt = expected_run_attempt or os.environ.get("GITHUB_RUN_ATTEMPT")
    if not isinstance(expected_source_commit, str) or not SHA1.fullmatch(expected_source_commit):
        reject("expected source commit must be an explicit full Git SHA")
    if not isinstance(expected_run_id, str) or not expected_run_id.isdecimal() or int(expected_run_id) <= 0:
        reject("expected run ID must be explicit and positive")
    if not isinstance(expected_run_attempt, str) or not expected_run_attempt.isdecimal() or int(expected_run_attempt) <= 0:
        reject("expected run attempt must be explicit and positive")

    sample = read_config("sample.json", list, [])
    population = read_config("population.json", list, [])
    sampling = read_config("sampling.json", dict, {})
    frozen_manifest = read_config("expected_source_manifest.json", dict, {})
    minisat_manifest = read_config("expected_minisat_source_manifest.json", dict, {})
    if not minisat_manifest or not all(valid_digest(value) for value in minisat_manifest.values()):
        reject("invalid pinned MiniSAT source manifest")
    try:
        manifest = source_manifest(solver_dir)
        if not manifest or "Makefile" not in manifest:
            reject("solver source tree or Makefile is missing")
        if manifest != frozen_manifest:
            reject("current solver sources differ from expected_source_manifest.json")
    except OSError as error:
        reject("cannot hash solver sources: %s" % error)
        manifest = {}
    if not frozen_manifest or not all(valid_digest(value) for value in frozen_manifest.values()):
        reject("invalid expected source manifest")
    harness_hashes = {}
    for key, name in (("checker_sha256", "validate_model.cpp"), ("evaluator_sha256", "run_pair.py")):
        try:
            harness_hashes[key] = digest(config_dir / name)
        except OSError as error:
            reject("cannot hash %s: %s" % (name, error))
    for key, expected_value in (("sample_count", SAMPLE_COUNT), ("population_count", POPULATION_COUNT),
                                ("seed", SAMPLE_SEED), ("track", "main_2025"),
                                ("filtered_by_size_difficulty_or_result", False)):
        if type(sampling.get(key)) is not type(expected_value) or sampling.get(key) != expected_value:
            reject("invalid sampling metadata: " + key)
    for key, name in (("sample_sha256", "sample.json"), ("population_sha256", "population.json"),
                      ("population_uri_sha256", "track_main_2025.uri")):
        try:
            if not valid_digest(sampling.get(key)) or sampling[key] != digest(config_dir / name):
                reject("configuration SHA-256 mismatch: " + name)
        except OSError as error:
            reject("cannot verify %s: %s" % (name, error))

    population_valid = len(population) == POPULATION_COUNT
    population_hashes = []
    for row in population:
        if (not isinstance(row, dict) or not isinstance(row.get("hash"), str)
                or not GBD_HASH.fullmatch(row["hash"])
                or row.get("result") not in ("sat", "unsat", "unknown")
                or "main_2025" not in str(row.get("track", "")).split(",")
                or not isinstance(row.get("filename"), str) or not isinstance(row.get("family"), str)):
            population_valid = False
        else:
            population_hashes.append(row["hash"])
    if len(set(population_hashes)) != POPULATION_COUNT:
        population_valid = False
    if not population_valid:
        reject("population must contain exactly 400 distinct Main Track 2025 instances")
    try:
        uri_hashes = [line.strip().rsplit("/", 1)[-1]
                      for line in (config_dir / "track_main_2025.uri").read_text().splitlines() if line.strip()]
        if len(uri_hashes) != POPULATION_COUNT or sorted(uri_hashes) != sorted(population_hashes):
            reject("population metadata differs from official URI list")
    except (OSError, UnicodeError) as error:
        reject("cannot read population URI list: %s" % error)
    if population_valid:
        selected = random.Random(SAMPLE_SEED).sample(sorted(population, key=lambda row: row["hash"]), SAMPLE_COUNT)
        recomputed_sample = [
            {"index": index, "hash": row["hash"], "expected": row["result"],
             "filename": row["filename"], "family": row["family"],
             "url": "https://benchmark-database.de/file/" + row["hash"] + "?context=cnf"}
            for index, row in enumerate(selected)]
        if sample != recomputed_sample:
            reject("sample differs from uniform sampling without replacement with frozen seed")
    expected = {}
    sample_hashes = []
    if len(sample) != SAMPLE_COUNT:
        reject("expected 100 sampled instances, got %d" % len(sample))
    for item in sample:
        if (not isinstance(item, dict) or type(item.get("index")) is not int
                or not isinstance(item.get("hash"), str)):
            reject("invalid sample entry")
            continue
        if item["index"] in expected:
            reject("duplicate sample index: %d" % item["index"])
        expected[item["index"]] = item
        sample_hashes.append(item["hash"])
    if set(expected) != set(range(SAMPLE_COUNT)) or len(set(sample_hashes)) != SAMPLE_COUNT:
        reject("sample must contain indices 0 through 99 and 100 distinct hashes")
    hashes_digest = hashlib.sha256(("\n".join(sample_hashes) + "\n").encode()).hexdigest()
    if sampling.get("sample_hashes_sha256") != hashes_digest:
        reject("sample hash order differs from sampling metadata")

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
            invalid_artifacts.append({"path": str(path), "error": str(error), "raw_text": raw})
            continue
        raw_records.append(record)
        artifact_paths.append(str(path))
        if not isinstance(record, dict) or type(record.get("index")) is not int:
            reject("artifact requires an object with integer index: %s" % path)
            continue
        index = record["index"]
        if index not in expected:
            reject("unexpected result index %d" % index)
            continue
        if index in records:
            reject("duplicate result index %d" % index)
            continue
        records[index] = (record, path.parent)
    missing = sorted(set(expected) - set(records))
    if missing:
        errors.append("missing result indices: " + ", ".join(map(str, missing)))
    if len(raw_records) > SAMPLE_COUNT:
        reject("expected exactly 100 result files, got %d" % len(raw_records))

    counts = {solver: Counter({outcome: 0 for outcome in OUTCOMES}) for solver in SOLVERS}
    validation_counts = {solver: Counter() for solver in SOLVERS}
    overlap = {"both_solved_validated": 0, "uatu_only": 0, "minisat_only": 0, "neither_solved_validated": 0}
    artifact_checks = []
    penalties = {solver: [] for solver in SOLVERS}
    build_commands = None
    for index, (record, directory) in sorted(records.items()):
        item = expected[index]
        label = "index %d" % index
        if record.get("benchmark") != item:
            reject("benchmark mismatch at " + label)
        if record.get("sampling") != sampling:
            reject("sampling metadata mismatch at " + label)
        if record.get("source_manifest") != manifest or record.get("source_manifest_sha256") != canonical_digest(manifest):
            reject("source manifest mismatch at " + label)
        for key, value in (("source_commit", expected_source_commit), ("github_run_id", expected_run_id),
                           ("github_run_attempt", expected_run_attempt), ("minisat_commit", MINISAT_COMMIT),
                           ("solver_base_commit", UATU_BASE_COMMIT),
                           ("minisat_source_manifest", minisat_manifest),
                           ("base_directory", "cpu/ver_4"), ("implementation_stages", [1, 2, 3, 4])):
            if key not in record or record[key] != value or type(record[key]) is not type(value):
                reject("%s mismatch at %s" % (key, label))
        if record.get("source_directory") != "cpu/ver_5":
            reject("unexpected solver source directory at " + label)
        for key, value in harness_hashes.items():
            if record.get(key) != value:
                reject("%s mismatch at %s" % (key, label))
        expected_order = list(SOLVERS) if index % 2 == 0 else list(reversed(SOLVERS))
        if record.get("order") != expected_order:
            reject("solver execution order mismatch at " + label)
        commands = record.get("build_commands")
        if (not isinstance(commands, dict) or set(commands) != set(SOLVERS)
                or not all(isinstance(value, str) and value for value in commands.values())):
            reject("missing build commands at " + label)
        elif build_commands is None:
            build_commands = commands
        elif commands != build_commands:
            reject("inconsistent build commands at " + label)
        binaries = record.get("binary_sha256")
        if not isinstance(binaries, dict) or set(binaries) != set(SOLVERS) or not all(valid_digest(v) for v in binaries.values()):
            reject("missing binary provenance at " + label)
        input_info = record.get("input")
        if not isinstance(input_info, dict):
            reject("missing input provenance at " + label)
            input_info = {}
        if input_info.get("url") != item.get("url"):
            reject("input URL mismatch at " + label)
        for key in ("compressed_sha256", "cnf_sha256"):
            if not valid_digest(input_info.get(key)):
                reject("invalid input %s at %s" % (key, label))
        for key in ("compressed_bytes", "cnf_bytes"):
            if type(input_info.get(key)) is not int or input_info[key] <= 0:
                reject("invalid input %s at %s" % (key, label))
        artifact_manifest = record.get("artifact_sha256")
        actual_hashes = {}
        if not isinstance(artifact_manifest, dict) or not all(name in artifact_manifest for name in ("uatu.log", "minisat.log")):
            reject("missing artifact manifest at " + label)
            artifact_manifest = {}
        for name, value in artifact_manifest.items():
            if name not in ("uatu.log", "minisat.log", "minisat.model") or not valid_digest(value):
                reject("invalid artifact manifest entry at %s: %r" % (label, name))
                continue
            path = directory / name
            try:
                if path.is_symlink():
                    raise ValueError("symbolic link is not an artifact file")
                actual_hashes[name] = digest(path)
                if actual_hashes[name] != value:
                    reject("artifact SHA-256 mismatch at %s: %s" % (label, name))
            except (OSError, ValueError) as error:
                reject("cannot verify artifact at %s %s: %s" % (label, name, error))
        artifact_checks.append({"index": index, "sha256": actual_hashes})
        pair = {solver: record.get(solver) for solver in SOLVERS}
        if all(isinstance(pair[solver], dict) for solver in SOLVERS):
            answers = {pair[solver].get("outcome") for solver in SOLVERS
                       if isinstance(pair[solver].get("outcome"), str)}
            if answers == {"sat", "unsat"}:
                reject("SAT/UNSAT answer disagreement at " + label)
            affinity = [pair[s].get("cpu_affinity") for s in SOLVERS]
            if any(type(cpu) is not int or cpu < 0 for cpu in affinity) or affinity[0] != affinity[1]:
                reject("pair CPU affinity mismatch at " + label)
        solved = {}
        for solver in SOLVERS:
            result = pair[solver]
            solver_label = "%s index %d" % (solver, index)
            solved[solver] = False
            if not isinstance(result, dict):
                reject("missing solver result: " + solver_label)
                counts[solver]["missing"] += 1
                continue
            outcome = result.get("outcome")
            validation = result.get("validation")
            if not isinstance(outcome, str) or outcome not in OUTCOMES:
                reject("invalid outcome for " + solver_label)
                counts[solver]["unknown"] += 1
                continue
            counts[solver][outcome] += 1
            validation_counts[solver][str(validation)] += 1
            if not isinstance(validation, str) or validation not in VALIDATIONS:
                reject("missing or unknown validation for " + solver_label)
            compatible_validations = {
                "sat": {"validated_sat_model", "wrong_result", "invalid_model"},
                "unsat": {"matches_known_unsat", "matches_other_unsat", "unverified_unsat", "wrong_result"},
                "timeout": {"unresolved"}, "resource_limit": {"unresolved"},
                "execution_error": {"execution_error"},
            }
            if not isinstance(validation, str) or validation not in compatible_validations[outcome]:
                reject("outcome and validation are inconsistent for " + solver_label)
            if type(result.get("timeout_seconds")) not in (float, int) or result.get("timeout_seconds") != TIMEOUT_SECONDS:
                reject("timeout must be 1000 seconds for " + solver_label)
            if type(result.get("memory_limit_bytes")) is not int or result.get("memory_limit_bytes") != MEMORY_LIMIT_BYTES:
                reject("memory limit must be 12 GiB for " + solver_label)
            for key in ("wall_seconds", "user_seconds", "system_seconds", "max_rss_kib"):
                if not finite_nonnegative(result.get(key)):
                    reject("invalid %s for %s" % (key, solver_label))
            wall = result.get("wall_seconds")
            if type(result.get("external_timeout")) is not bool or type(result.get("returncode")) is not int:
                reject("missing process exit evidence for " + solver_label)
            command = result.get("command")
            command_valid = (isinstance(command, list) and all(isinstance(arg, str) for arg in command)
                             and len(command) == (2 if solver == "uatu" else 4))
            if command_valid:
                command_valid = (Path(command[0]).name == ("uatu_solver" if solver == "uatu" else "minisat_release")
                                 and Path(command[1 if solver == "uatu" else 2]).name == "input.cnf")
                if solver == "minisat":
                    command_valid = command_valid and command[1] == "-verb=0" and Path(command[3]).name == "minisat.model"
            if not command_valid:
                reject("unexpected solver command for " + solver_label)
            log_name = solver + ".log"
            if not valid_digest(result.get("log_sha256")) or result["log_sha256"] != actual_hashes.get(log_name):
                reject("solver log SHA-256 mismatch for " + solver_label)
            try:
                with (directory / log_name).open(errors="replace") as log:
                    statuses = set()
                    resource_lines = []
                    for line in log:
                        line = line.rstrip("\r\n")
                        if line in ("SATISFIABLE", "UNSATISFIABLE"):
                            statuses.add(line)
                        if outcome == "resource_limit":
                            resource_lines.append(line)
                if outcome in ("sat", "unsat") and statuses != {"SATISFIABLE" if outcome == "sat" else "UNSATISFIABLE"}:
                    reject("solver log does not contain exactly the declared answer for " + solver_label)
                if outcome == "resource_limit":
                    oom_prefixes = ("c OUT OF MEMORY during ", "c RESOURCE LIMIT: container size exceeded during ")
                    if solver == "uatu":
                        resource_valid = (any(line.startswith(oom_prefixes) for line in resource_lines)
                                          and result.get("resource_reason") == "Uatu allocation/container limit diagnostic")
                    else:
                        signature = ["WARNING: for repeatability, setting FPU to use double precision", "=" * 79, "INDETERMINATE"]
                        resource_valid = (resource_lines in (signature, signature[1:]) and command_valid
                                          and result.get("resource_reason") == "Pinned MiniSAT OutOfMemoryException signature, simp/Main.cc lines 206-210")
                    if not resource_valid or result.get("returncode") != 0 or statuses:
                        reject("resource limit lacks the pinned allocation-failure signature for " + solver_label)
            except OSError as error:
                reject("cannot inspect solver log for %s: %s" % (solver_label, error))
            if outcome == "execution_error":
                reject("execution error for " + solver_label)
            if validation in ("wrong_result", "invalid_model"):
                reject("%s for %s" % (validation, solver_label))
            if outcome in ("timeout", "resource_limit"):
                if validation != "unresolved":
                    reject("unresolved outcome has inconsistent validation for " + solver_label)
                if outcome == "timeout" and not (result.get("external_timeout") is True or
                                                  finite_nonnegative(wall) and wall >= TIMEOUT_SECONDS):
                    reject("timeout lacks cutoff evidence for " + solver_label)
                if outcome == "resource_limit" and (result.get("external_timeout") is not False or
                                                       not finite_nonnegative(wall) or wall > TIMEOUT_SECONDS):
                    reject("resource limit has inconsistent timing evidence for " + solver_label)
                penalties[solver].append(2.0 * TIMEOUT_SECONDS)
                continue
            if outcome not in ("sat", "unsat"):
                continue
            time_valid = finite_nonnegative(wall) and wall <= TIMEOUT_SECONDS and result.get("external_timeout") is False
            if not time_valid:
                reject("solved answer exceeded cutoff or lacks timing evidence for " + solver_label)
            if result.get("returncode") != (10 if outcome == "sat" else 20):
                reject("solved answer has wrong exit code for " + solver_label)
            expected_answer = item.get("expected")
            if expected_answer in ("sat", "unsat") and outcome != expected_answer:
                reject("answer contradicts known status for " + solver_label)
            answer_valid = False
            if outcome == "sat":
                checked = result.get("model_check")
                model_name = "uatu.log" if solver == "uatu" else "minisat.model"
                answer_valid = (validation == "validated_sat_model" and isinstance(checked, dict)
                                and type(checked.get("returncode")) is int and checked["returncode"] == 0
                                and isinstance(checked.get("output"), str)
                                and re.fullmatch(r"VALID: vars=\d+ clauses=\d+\n?", checked["output"]) is not None
                                and valid_digest(checked.get("model_sha256"))
                                and checked["model_sha256"] == actual_hashes.get(model_name)
                                and checked.get("checker_sha256") == harness_hashes.get("checker_sha256")
                                and checked.get("input_sha256") == input_info.get("cnf_sha256"))
            elif validation == "matches_known_unsat":
                answer_valid = expected_answer == "unsat"
            elif validation == "matches_other_unsat":
                other = pair["minisat" if solver == "uatu" else "uatu"]
                answer_valid = (expected_answer == "unknown" and isinstance(other, dict)
                                and other.get("outcome") == "unsat"
                                and other.get("returncode") == 20 and other.get("external_timeout") is False
                                and finite_nonnegative(other.get("wall_seconds"))
                                and other["wall_seconds"] <= TIMEOUT_SECONDS)
            elif validation == "unverified_unsat":
                other = pair["minisat" if solver == "uatu" else "uatu"]
                if (expected_answer == "unknown" and isinstance(other, dict)
                        and other.get("outcome") in ("timeout", "resource_limit", "execution_error")):
                    unverified = True
                    errors.append("UNSAT lacks known or reference-solver confirmation for " + solver_label)
                else:
                    reject("unverified UNSAT label contradicts available answer evidence for " + solver_label)
            if not answer_valid and not (outcome == "unsat" and validation == "unverified_unsat"):
                reject("unvalidated solved answer for " + solver_label)
            if answer_valid and time_valid and (expected_answer == "unknown" or expected_answer == outcome):
                solved[solver] = True
                counts[solver]["solved_validated"] += 1
                penalties[solver].append(wall)
        validations = [pair[s].get("validation") if isinstance(pair[s], dict) else None for s in SOLVERS]
        pair_expected = "complete" if all(v in GOOD_VALIDATIONS for v in validations if isinstance(v, str)) and all(isinstance(v, str) for v in validations) else "invalid"
        if record.get("validation") != pair_expected:
            reject("pair validation is missing or inconsistent at " + label)
        if solved["uatu"] and solved["minisat"]:
            overlap["both_solved_validated"] += 1
        elif solved["uatu"]:
            overlap["uatu_only"] += 1
        elif solved["minisat"]:
            overlap["minisat_only"] += 1
        else:
            overlap["neither_solved_validated"] += 1
    complete = not missing and len(records) == SAMPLE_COUNT and len(raw_records) == SAMPLE_COUNT
    status = "invalid" if invalid else "incomplete" if not complete else "unverified" if unverified else "complete"
    for solver in SOLVERS:
        counts[solver].setdefault("solved_validated", 0)
        counts[solver]["executed"] = sum(counts[solver][key] for key in OUTCOMES)
    scores = None
    comparison = None
    if status == "complete":
        if any(len(penalties[solver]) != SAMPLE_COUNT for solver in SOLVERS):
            status = "invalid"
            errors.append("PAR-2 requires exactly 100 validated or resource-limited outcomes per solver")
        else:
            scores = {solver: {
                "par2_total_seconds": math.fsum(penalties[solver]),
                "par2_mean_seconds": math.fsum(penalties[solver]) / SAMPLE_COUNT,
                "solved": counts[solver]["solved_validated"],
                "unsolved": SAMPLE_COUNT - counts[solver]["solved_validated"],
                "per_instance_penalties_seconds": penalties[solver],
            } for solver in SOLVERS}
            uatu_score = scores["uatu"]["par2_mean_seconds"]
            minisat_score = scores["minisat"]["par2_mean_seconds"]
            comparison = {
                "uatu_outperforms_minisat": uatu_score < minisat_score,
                "minisat_over_uatu_par2_ratio": minisat_score / uatu_score if uatu_score > 0 else None,
                "uatu_par2_change_percent": 100.0 * (uatu_score / minisat_score - 1.0) if minisat_score > 0 else None,
                "ratio_definition": "MiniSAT mean PAR-2 divided by Uatu mean PAR-2; greater than 1 favors Uatu",
            }
    return {
        "status": status, "errors": errors, "sample_count": len(sample), "record_count": len(raw_records),
        "unique_result_count": len(records), "missing_indices": missing,
        "source_commit": expected_source_commit, "solver_base_commit": UATU_BASE_COMMIT,
        "minisat_commit": MINISAT_COMMIT, "minisat_source_manifest": minisat_manifest,
        "build_commands": build_commands, "github_run_id": expected_run_id,
        "github_run_attempt": expected_run_attempt, "source_manifest": manifest,
        "harness_sha256": harness_hashes, "sampling": sampling, "population": population, "sample": sample,
        "timeout_seconds": TIMEOUT_SECONDS, "memory_limit_bytes": MEMORY_LIMIT_BYTES,
        "validation_definition": "SAT models checked against every original clause; UNSAT compared with known GBD status or the pinned MiniSAT result. No UNSAT proof checking. Timeouts and memory limits are unresolved, not correctness passes.",
        "par2_definition": "For each of the 100 sampled instances, use validated solving wall time if solved within 1000 seconds; use 2000 seconds for timeout or memory limit. Mean PAR-2 is the total divided by 100. Invalid/incomplete/unverified experiments publish no score.",
        "scores": scores, "comparison": comparison,
        "counts": counts, "validation_counts": validation_counts, "pair_solved_overlap": overlap,
        "records": raw_records, "artifact_paths": artifact_paths, "artifact_checks": artifact_checks,
        "invalid_artifacts": invalid_artifacts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--solver-dir", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--expected-run-id")
    parser.add_argument("--expected-run-attempt")
    args = parser.parse_args()
    summary = collect(args.artifacts, args.solver_dir, args.config_dir, args.expected_source_commit,
                      args.expected_run_id, args.expected_run_attempt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: summary[key] for key in
                      ("status", "sample_count", "record_count", "counts", "validation_counts", "scores", "comparison", "errors")}, indent=2))
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
