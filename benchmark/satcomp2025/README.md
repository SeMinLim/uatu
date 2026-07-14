# SAT Competition 2025 Main Track

This benchmark set is the designated **frozen final-evaluation set** for Uatu.

Do not tune heuristics or solver parameters using these results. Development and tuning should be performed with the SAT Competition 2024 Main Track set, after which the implementation and configuration should be frozen before evaluating here.

## Requirements

```bash
sudo apt install wget xz-utils
```

## Download and extract

The workflow deliberately downloads compressed instances first and extracts them before the solver is run. Uatu does not read `.xz` files directly.

```bash
cd benchmark/satcomp2025

# Download track_main_2025.uri and all .cnf.xz instances.
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
satcomp2025/
├── track_main_2025.uri
├── compressed/    # downloaded .cnf.xz files
└── cnf/           # decompressed .cnf files used by Uatu
```

Downloaded and decompressed files are ignored by Git.

## Run Uatu

```bash
cd cpu/ver_2
make run CNF=../../benchmark/satcomp2025/cnf/<instance>.cnf TIMEOUT=5000
```

For a fair report, record the frozen commit, compiler flags, hardware, timeout, solved count, SAT/UNSAT split, and PAR-2. Validate SAT models and independently verify UNSAT results or proof certificates.
