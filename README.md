# Uatu

> A compact CDCL SAT solver and a CPU–FPGA hardware/software co-design research platform.

Uatu investigates how to accelerate Boolean Constraint Propagation (BCP) on an FPGA while preserving the flexibility of a software CDCL solver. The project intentionally keeps the host solver smaller and easier to reason about than feature-heavy production solvers, while aiming for competitive performance through a carefully selected set of heuristics.

The long-term target is a heterogeneous system in which the CPU remains responsible for search control and modern software heuristics, while an FPGA implements a persistent BCP engine.

## Project motivation

A stand-alone FPGA SAT solver can provide high propagation throughput, but it must also fit the evolving clause database, assignment state, implication information, and solver heuristics inside a constrained hardware memory system. This becomes difficult for real-world CDCL workloads because learned clauses are created and deleted dynamically.

Uatu takes a different approach:

- keep CDCL search control and flexible heuristics in software;
- offload the dominant propagation work to an FPGA;
- use FPGA HBM as a bounded propagation database rather than forcing the entire solver into on-chip memory;
- communicate through persistent, asynchronous, and batched interfaces instead of issuing a PCIe round trip for every individual implication;
- preserve support for large CNF instances and dynamically changing learned clauses.

The planned hardware target is an **AMD Alveo U50** with approximately **8 GB of HBM**.

## Design philosophy

Uatu is not intended to become a reimplementation of every feature in MiniSAT, CaDiCaL, or Kissat. Its software solver follows four principles:

1. **Compact CDCL core**  
   Keep the implementation small enough that search state, ownership, and the CPU–FPGA boundary remain explicit.

2. **Deep-search preservation**  
   Avoid discarding a useful assignment trail too aggressively. The current CPU prototype resets short-term LBD statistics without necessarily performing a conventional root-level restart.

3. **Lightweight diversification**  
   Use phase saving and a soft rephasing policy to influence future decisions while preserving the current trail.

4. **Co-design-friendly state**  
   Favor solver structures that can later be mirrored, streamed, or managed efficiently across CPU memory and FPGA HBM.

MiniSAT remains an important architectural reference and external baseline, but Uatu's goal is to retain a simpler solver whose behavior can be deliberately co-designed with an FPGA accelerator.

## Current status

| Component | Status |
|---|---|
| Compact CPU CDCL solver | Available |
| DIMACS CNF parser | Available |
| Two-watched-literal BCP | Available |
| First-UIP clause learning | Available |
| VSIDS-style branching | Available |
| Phase saving and soft rephasing | Available |
| LBD scoring and clause reduction | Available |
| FPGA BCP engine | Research/design phase |
| Asynchronous CPU–FPGA protocol | Research/design phase |
| Alveo U50 HBM integration | Planned |

The actively documented C++ prototype is located in:

```text
cpu/cpp/ver_1/
├── main.cpp
├── solver.cpp
├── solver.h
└── Makefile
```

## CPU solver

The current solver is a compact, MiniSAT-style CDCL implementation with the following components.

### Conflict-driven clause learning

- First-UIP conflict analysis
- learned-clause generation
- non-chronological backtracking
- reason and decision-level tracking through the assignment trail

### Boolean Constraint Propagation

- two watched literals per non-unit clause
- blocker-based satisfied-clause fast path
- dynamic watcher relocation
- propagation queue represented by the assignment trail

### Variable decisions

- VSIDS-style variable activity
- max-heap variable selection
- custom two-stage activity bumping around conflict analysis
- phase saving

### Clause quality and database control

- Literal Block Distance (LBD) computation
- recent-LBD and global-LBD statistics
- learned-clause reduction
- root-level backtracking coupled primarily to clause database reduction

### Search diversification

The current `ver_1` source retains the historical function name `restart()`, but its active behavior preserves the assignment trail and resets the recent-LBD window. It is therefore better understood as a **recent-LBD reset**, not as a conventional hard restart.

Rephasing is a lightweight Uatu-specific policy inspired by phase-diversification techniques used in modern SAT solvers. It is **not** a line-for-line implementation of CaDiCaL's full rephasing schedule.

## Build

### Requirements

- Linux or another POSIX-like environment
- GNU Make
- a C++ compiler with C++11 support or newer

### Compile

```bash
git clone https://github.com/SeMinLim/uatu.git
cd uatu/cpu/cpp/ver_1
make
```

The executable is generated at:

```text
obj/main
```

The checked-in Makefile currently builds the C++ sources with `g++`, warnings enabled, debug symbols, and `-O2` optimization.

## Run

Uatu accepts a SAT instance in DIMACS CNF format:

```bash
./obj/main /path/to/instance.cnf
```

Example:

```bash
./obj/main example.cnf
```

The program reports one of:

```text
SATISFIABLE
UNSATISFIABLE
UNSOLVED
```

It also prints basic solver statistics:

```text
Conflicts
Decisions
Unit Propagations
BCP Calls
```

For SAT instances, model printing is implemented but disabled by default in `main.cpp`. It can be enabled by uncommenting:

```cpp
S.printModel();
```

## Planned CPU–FPGA partition

The intended Uatu architecture keeps a clear ownership boundary.

### CPU responsibilities

- variable decision heuristic
- First-UIP conflict analysis
- learned-clause generation and minimization policy
- phase saving and rephasing
- clause quality evaluation and deletion policy
- restart/reduction policy
- authoritative solver control flow

### FPGA responsibilities

- persistent assignment mirror for BCP
- propagation event queue
- affected-clause lookup
- clause-state inspection
- unit and conflict detection
- implied-literal and reason generation
- HBM-backed active propagation database
- backtrack synchronization for FPGA-owned propagation state

### Communication model

The desired interface is command- and event-oriented rather than function-call-oriented.

```text
CPU -> FPGA
  ASSIGN
  BACKTRACK
  ADD_CLAUSE
  DELETE_CLAUSE
  PROPAGATE

FPGA -> CPU
  IMPLIED_LITERAL
  CONFLICT
  PROPAGATION_DONE
```

The FPGA should continue propagation internally until a conflict or a fixed point is reached. This avoids returning to the CPU for every individual unit implication.

## Why BCP?

BCP is repeatedly executed after decisions and learned-clause assertions, and it often accounts for a large portion of CDCL runtime. The expensive part is not the final `unit` condition alone. The complete propagation workload includes:

1. mapping an assigned literal to affected clauses;
2. reading and updating propagation metadata;
3. skipping already satisfied clauses;
4. identifying unit or conflicting clauses;
5. extracting the implied literal and its reason;
6. enqueuing new implications and continuing to a fixed point.

Uatu therefore treats the FPGA component as a **persistent BCP event engine**, not as a stateless unit-clause checker.

## Evaluation plan

A complete Uatu evaluation should distinguish algorithmic improvements from hardware acceleration.

### Matched-code comparison

```text
Uatu CPU-only
vs.
Uatu CPU–FPGA
```

This comparison isolates the benefit and cost of BCP offloading.

### External software references

```text
MiniSAT
CaDiCaL
Kissat
```

These solvers provide context for absolute SAT-solving performance, but they do not replace the matched-code CPU baseline.

### Hardware reference

SAT-Accel is an important comparison point because it implements a stand-alone modern SAT solver on an FPGA. Uatu targets a different design point: a larger, software-controlled heterogeneous system with FPGA-accelerated propagation.

Metrics of interest include:

- solved instances and PAR-2;
- end-to-end runtime;
- BCP runtime and throughput;
- CPU–FPGA traffic and queue depth;
- PCIe synchronization overhead;
- HBM capacity and bandwidth utilization;
- learned-clause growth and deletion behavior;
- FPGA resource utilization and power.

## Roadmap

- [ ] stabilize a reproducible compact CPU baseline;
- [ ] separate release execution from fine-grained BCP profiling;
- [ ] replace randomized clause reduction with a reproducible lightweight policy;
- [ ] investigate lightweight learned-clause minimization;
- [ ] define stable clause identifiers for CPU–FPGA synchronization;
- [ ] design the persistent BCP event protocol;
- [ ] implement HBM-backed clause and propagation metadata storage;
- [ ] build the asynchronous host/FPGA command and response queues;
- [ ] evaluate on real-world and SAT Competition benchmark families;
- [ ] compare against the CPU-only Uatu solver, MiniSAT, CaDiCaL, Kissat, and SAT-Accel.

## Research references

- J. Marques-Silva, I. Lynce, and S. Malik, “Conflict-Driven Clause Learning SAT Solvers,” *Handbook of Satisfiability*, 2021.
- M. W. Moskewicz et al., “[Chaff: Engineering an Efficient SAT Solver](https://doi.org/10.1145/378239.379017),” DAC, 2001.
- N. Eén and N. Sörensson, “[An Extensible SAT-solver](https://doi.org/10.1007/978-3-540-24605-3_37),” SAT, 2003.
- K. Pipatsrisawat and A. Darwiche, “[A Lightweight Component Caching Scheme for Satisfiability Solvers](https://doi.org/10.1007/978-3-540-72788-0_20),” SAT, 2007.
- G. Audemard and L. Simon, “Predicting Learnt Clauses Quality in Modern SAT Solvers,” IJCAI, 2009.
- A. Biere, “CaDiCaL, Lingeling, Plingeling, Treengeling and YalSAT Entering the SAT Competition 2017,” SAT Competition, 2017.
- M. Lo, M.-C. F. Chang, and J. Cong, “[SAT-Accel: A Modern SAT Solver on a FPGA](https://doi.org/10.1145/3706628.3708869),” FPGA, 2025.

## Project scope

Uatu is an active research prototype. Interfaces, heuristics, memory representations, and the CPU–FPGA partition may change as the co-design is evaluated.