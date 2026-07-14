# SAT Solver

- Conflict-Driven Clause Learning
  - First UIP (Unit Implication Point) clause learning [Based on Chaff]
- Boolean Constraint Propagation
  - Lazy data structure (two watched literals) [Based on Chaff]
  - Two polarities, pinned position for watched literals, and blockers [Based on MiniSAT]
- Variable Decision
  - Conflict-Driven Branching Heuristics
    - VSIDS (Variable State Independent Decaying Sum) with heap data structure (Max-Heap) [Based on Chaff]
  - Progress Saving
    - A lightweight component caching scheme [Based on Pipatsrisawat2007]  
- Clause Deletion
  - Literal block distance scoring scheme [Based on Glucose]
- Restart
  - Dynamic search restart [Based on Glucose]
- Other Heuristics
  - Rephasing [Based on CaDiCaL]

------
### Mandatory Papers

- **[CDCL]** J. Marques-Silva, L. Inês, and M. Sharad, "Conflict-driven clause learning SAT solvers," Handbook of satisfiability, IOS press, 2021, 133-182.
- **[Chaff]** MW. Moskewicz et al, "Chaff: Engineering an efficient SAT solver," Proceedings of the 38th annual Design Automation Conference, 2001.
- **[MiniSAT]** N. Eén and S. Niklas, "An extensible SAT-solver," Lecture notes in computer science 2919.2004 (2004): 502-518.
- **[Phase Saving Technique]** K. Pipatsrisawat and D. Adnan, "A lightweight component caching scheme for satisfiability solvers," Theory and Applications of Satisfiability Testing–SAT 2007: 10th International Conference, Lisbon, Portugal, May 28-31, 2007.
- **[Glucose]** G. Audemard and S. Laurent, "Predicting learnt clauses quality in modern SAT solvers," Twenty-first international joint conference on artificial intelligence, 2009.
- **[Glucose]** G. Audemard and S. Laurent, "GLUCOSE: a solver that predicts learnt clauses quality," SAT Competition, 2009.
- **[CaDiCaL]** A. Biere, "Cadical, lingeling, plingeling, treengeling and yalsat entering the sat competition 2017," Proceedings of SAT Competition 14 (2017): 316-336.
