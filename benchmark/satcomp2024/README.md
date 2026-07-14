# SAT Competition 2024 Main Track

This benchmark set is the designated **heuristic-development and parameter-tuning set** for Uatu.

Use these instances to compare candidate restart, rephase, clause-management, minimization, and other solver policies. Solver code and parameters should be frozen before running the SAT Competition 2025 final-evaluation set.

## Requirements

```bash
sudo apt install wget xz-utils
```

## Download and extract

The workflow deliberately downloads compressed instances first and extracts them before the solver is run. Uatu does not read `.xz` files directly.

```bash
cd benchmark/satcomp2024

# Download track_main_2024.uri and all .cnf.xz instances.
bash download.sh download

# Decompress the downloaded instances into ./cnf.
bash download.sh extract
```

Run both steps with one command:

```bash
bash download.sh all
```

Generated layout:

```text
satcomp2024/
├── track_main_2024.uri
├── compressed/    # downloaded .cnf.xz files
└── cnf/           # decompressed .cnf files used by Uatu
```

Downloaded and decompressed files are ignored by Git.

## Run Uatu

```bash
cd cpu/ver_2
make run CNF=../../benchmark/satcomp2024/cnf/<instance>.cnf TIMEOUT=1000
```

Do not use this set as the sole final test set after tuning on it.
