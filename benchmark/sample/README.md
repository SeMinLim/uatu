# Sample benchmarks

This directory contains a small archive of CNF instances intended only for quick smoke tests, parser checks, and basic correctness experiments. These instances are not a substitute for SAT Competition benchmark suites and should not be used for final performance claims.

## Extract the sample set

The archive is committed as `benchmark.tar.gz`. Extract it before running a solver:

```bash
cd benchmark/sample
bash download.sh
```

The script preserves the archive and places the extracted DIMACS files in:

```text
benchmark/sample/cnf/
```

It accepts archives that contain either plain `.cnf` files or `.cnf.xz` files, including archives with nested directories.

## Run Uatu

From either CPU solver directory:

```bash
cd cpu/ver_1   # original solver
make run CNF=../../benchmark/sample/cnf/benchmark1.cnf
```

or:

```bash
cd cpu/ver_2   # improved solver
make run CNF=../../benchmark/sample/cnf/benchmark1.cnf
```

The default `CNF` value in both Makefiles points to this sample path.
