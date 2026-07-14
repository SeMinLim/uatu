# Benchmark sets

The benchmark directory is divided by purpose.

| Directory | Purpose |
|---|---|
| `sample/` | Small smoke-test instances for checking builds and basic solver behavior |
| `satcomp2024/` | Heuristic development and parameter-tuning set |
| `satcomp2025/` | Frozen final-evaluation set |

## Anti-overfitting policy

Use the SAT Competition 2024 Main Track benchmarks while developing or tuning heuristics. Freeze the solver implementation and its parameters before evaluating on the SAT Competition 2025 Main Track benchmarks.

Do not make heuristic or parameter decisions from the SAT Competition 2025 results and then report those same results as an unbiased final evaluation. This policy should also be stated in the repository's top-level README when that document is next revised.

Each subdirectory contains its own `README.md` and `download.sh`. Benchmark archives are downloaded and decompressed before invoking the solver; the solver itself is not responsible for compressed input.
