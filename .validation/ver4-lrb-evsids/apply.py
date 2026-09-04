from pathlib import Path


ROOT = Path('.')
VER4 = ROOT / 'cpu' / 'ver_4'


def replaceOnce( text, old, new, label ):
	if old not in text:
		raise SystemExit('patch point not found: ' + label)
	return text.replace(old, new, 1)


# Extend the shared variable-order heap and add LRB state.
headerPath = VER4 / 'solver.h'
header = headerPath.read_text()
header = replaceOnce(
	header,
	'''    \tvoid initialize( const double *s ) {
\t\tactivity = s;
\t}

    \tbool empty() const { return heap.size() == 0; }

    \tbool inHeap( int n ) const { return n < (int)pos.size() && pos[n] >= 0; }
    \t
\tvoid update( int x ) { up(pos[x]); }
''',
	'''    \tvoid initialize( const double *s ) {
\t\tactivity = s;
\t}

\tvoid rebuild( const double *s, int variableCount ) {
\t\tactivity = s;
\t\theap.clear();
\t\tpos.assign(variableCount + 1, -1);
\t\theap.reserve(variableCount);
\t\tfor ( int variable = 1; variable <= variableCount; variable ++ ) {
\t\t\tinsert(variable);
\t\t}
\t}

    \tbool empty() const { return heap.size() == 0; }
\tint top() const { return heap[0]; }

    \tbool inHeap( int n ) const { return n < (int)pos.size() && pos[n] >= 0; }
    \t
\tvoid update( int x ) {
\t\tif ( !inHeap(x) ) return;
\t\tup(pos[x]);
\t\tdown(pos[x]);
\t}
''',
	'generalized heap ordering'
)
header = replaceOnce(
	header,
	'''    \tdouble *activity = nullptr;                    // The variables' score for VSIDS
\tdouble var_inc = 0.0, var_decay = 0.0;                       // Parameter for VSIDS
\tdouble clause_inc = 0.0, clause_decay = 0.0;                 // Parameters for learnt-clause activity
    \tHeap vsids;                                    // Heap to select variable
''',
	'''    \tdouble *activity = nullptr;                    // The variables' score for EVSIDS
\tdouble var_inc = 0.0, var_decay = 0.0;               // Parameters for EVSIDS
\tdouble *lrbActivity = nullptr;                       // The variables' score for LRB
\tuint32_t *lrbTimestamp = nullptr;                   // Assignment or cancellation conflict stamp
\tuint32_t *lrbParticipated = nullptr;                // Conflict participation in one interval
\tuint32_t *lrbReasoned = nullptr;                    // Reason-side participation in one interval
\tdouble lrbStepSize = 0.0;                           // LRB moving-average step size
\tdouble lrbStepSizeDecrease = 0.0;                   // LRB step-size decrement per conflict
\tdouble lrbMinimumStepSize = 0.0;                    // Minimum LRB step size
\tunsigned long long lrbConflictClock = 0;            // Conflict clock for LRB intervals
\tunsigned long long branchingPropagations = 0;       // Search propagations for switching
\tunsigned long long branchingPhaseBudget = 0;        // Current propagation budget per mode
\tunsigned long long branchingNextSwitch = 0;         // Propagation count for next switch
\tlong long lrbDecisions = 0, evsidsDecisions = 0;    // Decisions by each heuristic
\tlong long lrbUpdates = 0;                           // Completed LRB interval updates
\tint branchingSwitches = 0;                          // Number of mode switches
\tbool useLRBBranching = true;                        // Active branching heuristic
\tdouble clause_inc = 0.0, clause_decay = 0.0;       // Parameters for learnt-clause activity
    \tHeap vsids;                                    // Shared variable-order heap
''',
	'LRB and EVSIDS state'
)
header = replaceOnce(
	header,
	'''\t\tdelete [] activity;
\t\tdelete [] watched_literals;
''',
	'''\t\tdelete [] activity;
\t\tdelete [] lrbActivity;
\t\tdelete [] lrbTimestamp;
\t\tdelete [] lrbParticipated;
\t\tdelete [] lrbReasoned;
\t\tdelete [] watched_literals;
''',
	'LRB state destruction'
)
header = replaceOnce(
	header,
	'''\tint  decide();                                            // Pick decision variable based on VSIDS
\tvoid update_score( int var, double coeff );               // Update variable activity
''',
	'''\tint  decide();                                            // Pick decision variable by LRB or EVSIDS
\tvoid initializeBranching();                                // Initialize LRB and switching state
\tvoid recordLRBAssignment( int variable );                  // Begin one LRB learning interval
\tvoid recordLRBConflict( const std::vector<int> &variables ); // Record one LRB conflict
\tvoid updateLRBOnUnassign( int variable );                  // Finish one LRB learning interval
\tvoid applyLRBLocalityDecay( int variable );                // Penalize stale variables
\tvoid updateBranchingMode();                                // Switch by propagation budget
\tvoid update_score( int var, double coeff );               // Update EVSIDS variable activity
''',
	'branching method declarations'
)
headerPath.write_text(header)


# Integrate both branching signals with the existing solver.
solverPath = VER4 / 'solver.cpp'
solver = solverPath.read_text()
solver = replaceOnce(
	solver,
	'''        var_inc = 1;
        var_decay = 0.8;
        clause_inc = 1.0;
''',
	'''        var_inc = 1;
        var_decay = 0.95;
        clause_inc = 1.0;
''',
	'canonical EVSIDS decay'
)
solver = replaceOnce(
	solver,
	'''        vsids.initialize(activity);
        value[0] = local_best[0] = saved[0] = 0;
''',
	'''        value[0] = local_best[0] = saved[0] = 0;
''',
	'defer heap initialization'
)
solver = replaceOnce(
	solver,
	'''                activity[i] = 0.0;
                vsids.insert(i);
        }
}

// Assign 'true' value to a certain literal
''',
	'''                activity[i] = 0.0;
        }
        initializeBranching();
}

// Assign 'true' value to a certain literal
''',
	'initialize hybrid branching'
)
solver = replaceOnce(
	solver,
	'''\tint var = abs(literal);
    \tvalue[var] = literal > 0 ? 1 : -1;
''',
	'''\tint var = abs(literal);
\tif ( !vivificationActive ) recordLRBAssignment(var);
    \tvalue[var] = literal > 0 ? 1 : -1;
''',
	'LRB assignment start'
)
solver = replaceOnce(
	solver,
	'''                                assign(firstWatch, level[abs(p)], cref);
                                if ( vivificationActive ) vivificationPropagations ++;
                                else unitPropagations ++;
''',
	'''                                assign(firstWatch, level[abs(p)], cref);
                                if ( vivificationActive ) {
                                        vivificationPropagations ++;
                                } else {
                                        unitPropagations ++;
                                        branchingPropagations ++;
                                }
''',
	'propagation switching clock'
)
start = solver.index('// Pick decision variable based on VSIDS\n')
end = solver.index('// Update variable activity\n', start)
solver = solver[:start] + '''// Pick a decision variable with the active branching heuristic
int Solver::decide( void ) {
\tupdateBranchingMode();

\tint next = -1;
\twhile ( next == -1 ) {
\t\tif ( vsids.empty() ) return 10;

\t\tconst int candidate = vsids.top();
\t\tif ( Value(candidate) != 0 ) {
\t\t\tvsids.pop();
\t\t\tcontinue;
\t\t}

\t\tif ( useLRBBranching ) {
\t\t\tapplyLRBLocalityDecay(candidate);
\t\t\tif ( vsids.top() != candidate ) continue;
\t\t}
\t\tnext = vsids.pop();
\t}

\tdecVarInTrail.push_back(trail.size());
\tif ( saved[next] ) next *= saved[next];

\tassign(next, static_cast<int>(decVarInTrail.size()), -1);
\tdecides ++;
\tif ( useLRBBranching ) lrbDecisions ++;
\telse evsidsDecisions ++;

\treturn 0;
}

''' + solver[end:]
solver = replaceOnce(
	solver,
	'''    \tif ( vsids.inHeap(var) ) vsids.update(var);
}

// Update learnt-clause activity
''',
	'''    \tif ( !useLRBBranching && vsids.inHeap(var) ) vsids.update(var);
}

// Update learnt-clause activity
''',
	'EVSIDS heap update'
)
solver = replaceOnce(
	solver,
	'''                        update_score(variable, 0.5);
                        bump.push_back(variable);
''',
	'''                        update_score(variable, 1.0);
                        bump.push_back(variable);
''',
	'single EVSIDS bump'
)
solver = replaceOnce(
	solver,
	'''        ++time_stamp;
        lbd = 0;
''',
	'''        recordLRBConflict(bump);

        ++time_stamp;
        lbd = 0;
''',
	'LRB conflict collection'
)
solver = replaceOnce(
	solver,
	'''        // Original second-stage bump retained after the ablation trial.
        for ( int variable : bump ) {
                if ( level[variable] >= backtrackLevel - 1 ) update_score(variable, 1.0);
        }

        return 0;
''',
	'''        return 0;
''',
	'remove duplicate EVSIDS bump'
)
solver = replaceOnce(
	solver,
	'''                saved[variable] = trail[i] > 0 ? 1 : -1;
                value[variable] = 0;
''',
	'''                updateLRBOnUnassign(variable);
                saved[variable] = trail[i] > 0 ? 1 : -1;
                value[variable] = 0;
''',
	'LRB interval completion'
)
solverPath.write_text(solver)


# LRB and EVSIDS switching implementation.
(VER4 / 'branching.cpp').write_text(r'''#include "solver.h"

#include <algorithm>
#include <cmath>
#include <climits>
#include <cstdlib>


#define LRB_INITIAL_STEP_SIZE 0.40
#define LRB_STEP_SIZE_DECREASE 0.000001
#define LRB_MINIMUM_STEP_SIZE 0.06
#define LRB_LOCALITY_DECAY 0.95
#define BRANCHING_INITIAL_PHASE_PROPAGATIONS 30000000ULL
#define BRANCHING_PHASE_GROWTH 1.10


// Read a positive propagation-budget option
static unsigned long long readPropagationBudget( const char *name,
\t\t\t\t\t\t unsigned long long defaultValue ) {
\tconst char *environment = getenv(name);
\tif ( environment == NULL ) return defaultValue;

\tchar *end = NULL;
\tconst unsigned long long parsed = strtoull(environment, &end, 10);
\tif ( end == environment || *end != '\0' || parsed == 0 ) return defaultValue;
\treturn parsed;
}

// Initialize LRB state and start the first LRB phase
void Solver::initializeBranching() {
\tlrbActivity = new double[vars + 1];
\tlrbTimestamp = new uint32_t[vars + 1];
\tlrbParticipated = new uint32_t[vars + 1];
\tlrbReasoned = new uint32_t[vars + 1];

\tlrbStepSize = LRB_INITIAL_STEP_SIZE;
\tlrbStepSizeDecrease = LRB_STEP_SIZE_DECREASE;
\tlrbMinimumStepSize = LRB_MINIMUM_STEP_SIZE;
\tlrbConflictClock = 0;
\tbranchingPropagations = 0;
\tbranchingPhaseBudget = readPropagationBudget(
\t\t"UATU_BRANCH_PHASE_PROPAGATIONS",
\t\tBRANCHING_INITIAL_PHASE_PROPAGATIONS
\t);
\tbranchingNextSwitch = branchingPhaseBudget;
\tlrbDecisions = 0;
\tevsidsDecisions = 0;
\tlrbUpdates = 0;
\tbranchingSwitches = 0;
\tuseLRBBranching = true;

\tlrbActivity[0] = 0.0;
\tlrbTimestamp[0] = 0;
\tlrbParticipated[0] = 0;
\tlrbReasoned[0] = 0;
\tfor ( int variable = 1; variable <= vars; variable ++ ) {
\t\tlrbActivity[variable] = 0.0;
\t\tlrbTimestamp[variable] = 0;
\t\tlrbParticipated[variable] = 0;
\t\tlrbReasoned[variable] = 0;
\t}

\tvsids.rebuild(lrbActivity, vars);
}

// Penalize a variable that has remained unassigned for several conflicts
void Solver::applyLRBLocalityDecay( int variable ) {
\tconst unsigned long long age = lrbConflictClock - lrbTimestamp[variable];
\tif ( age == 0 ) return;

\tlrbActivity[variable] *= pow(LRB_LOCALITY_DECAY, static_cast<double>(age));
\tlrbTimestamp[variable] = static_cast<uint32_t>(lrbConflictClock);
\tif ( useLRBBranching && vsids.inHeap(variable) ) vsids.update(variable);
}

// Start a new LRB learning interval when a variable is assigned
void Solver::recordLRBAssignment( int variable ) {
\tapplyLRBLocalityDecay(variable);
\tlrbTimestamp[variable] = static_cast<uint32_t>(lrbConflictClock);
\tlrbParticipated[variable] = 0;
\tlrbReasoned[variable] = 0;
}

// Record direct and reason-side conflict participation for LRB
void Solver::recordLRBConflict( const std::vector<int> &variables ) {
\tlrbConflictClock ++;
\tfor ( int variable : variables ) {
\t\tif ( lrbParticipated[variable] != UINT32_MAX ) lrbParticipated[variable] ++;
\t}

\t++time_stamp;
\tconst int learntStamp = time_stamp;
\tfor ( int literal : learnt ) mark[abs(literal)] = learntStamp;

\tfor ( int literal : learnt ) {
\t\tconst int variable = abs(literal);
\t\tconst int reasonClause = reason[variable];
\t\tif ( reasonClause < 0 ||
\t\t     reasonClause >= static_cast<int>(clauseDB.size()) ) continue;

\t\tconst Clause &reasonData = clauseDB[reasonClause];
\t\tfor ( int reasonLiteral : reasonData.literals ) {
\t\t\tconst int reasonVariable = abs(reasonLiteral);
\t\t\tif ( level[reasonVariable] == 0 ||
\t\t\t     mark[reasonVariable] == learntStamp ) continue;

\t\t\tmark[reasonVariable] = learntStamp;
\t\t\tif ( lrbReasoned[reasonVariable] != UINT32_MAX ) {
\t\t\t\tlrbReasoned[reasonVariable] ++;
\t\t\t}
\t\t}
\t}

\tif ( lrbStepSize > lrbMinimumStepSize ) {
\t\tlrbStepSize = std::max(
\t\t\tlrbMinimumStepSize,
\t\t\tlrbStepSize - lrbStepSizeDecrease
\t\t);
\t}
}

// Finish one LRB interval when a search assignment is removed
void Solver::updateLRBOnUnassign( int variable ) {
\tconst unsigned long long age = lrbConflictClock - lrbTimestamp[variable];
\tif ( age > 0 ) {
\t\tconst double reward =
\t\t\t(static_cast<double>(lrbParticipated[variable]) +
\t\t\t static_cast<double>(lrbReasoned[variable])) /
\t\t\tstatic_cast<double>(age);
\t\tlrbActivity[variable] =
\t\t\tlrbStepSize * reward +
\t\t\t(1.0 - lrbStepSize) * lrbActivity[variable];
\t\tlrbUpdates ++;
\t\tif ( useLRBBranching && vsids.inHeap(variable) ) vsids.update(variable);
\t}
\tlrbTimestamp[variable] = static_cast<uint32_t>(lrbConflictClock);
}

// Alternate LRB and EVSIDS without changing the current assignment trail
void Solver::updateBranchingMode() {
\twhile ( branchingPropagations >= branchingNextSwitch ) {
\t\tuseLRBBranching = !useLRBBranching;
\t\tbranchingSwitches ++;

\t\tif ( branchingSwitches >= 2 ) {
\t\t\tconst long double grown =
\t\t\t\tstatic_cast<long double>(branchingPhaseBudget) *
\t\t\t\tBRANCHING_PHASE_GROWTH;
\t\t\tbranchingPhaseBudget = grown >= ULLONG_MAX
\t\t\t\t? ULLONG_MAX : static_cast<unsigned long long>(ceil(grown));
\t\t}

\t\tif ( ULLONG_MAX - branchingNextSwitch < branchingPhaseBudget ) {
\t\t\tbranchingNextSwitch = ULLONG_MAX;
\t\t} else {
\t\t\tbranchingNextSwitch += branchingPhaseBudget;
\t\t}

\t\tvsids.rebuild(useLRBBranching ? lrbActivity : activity, vars);
\t\tif ( branchingNextSwitch == ULLONG_MAX ) break;
\t}
}
''')


mainPath = VER4 / 'main.cpp'
main = mainPath.read_text()
main = replaceOnce(
	main,
	'''\tprintf( "Dynamic LBD Updates  : %lld\\n", solver.dynamicLBDUpdates );
\tprintf( "Active Clauses       : %zu\\n", solver.clauseDB.size() );
''',
	'''\tprintf( "Dynamic LBD Updates  : %lld\\n", solver.dynamicLBDUpdates );
\tprintf( "LRB Decisions        : %lld\\n", solver.lrbDecisions );
\tprintf( "EVSIDS Decisions     : %lld\\n", solver.evsidsDecisions );
\tprintf( "LRB Updates          : %lld\\n", solver.lrbUpdates );
\tprintf( "Branching Switches   : %d\\n", solver.branchingSwitches );
\tprintf( "Branching Propagations: %llu\\n", solver.branchingPropagations );
\tprintf( "Active Branching     : %s\\n",
\t\tsolver.useLRBBranching ? "LRB" : "EVSIDS"
\t);
\tprintf( "Active Clauses       : %zu\\n", solver.clauseDB.size() );
''',
	'branching statistics'
)
mainPath.write_text(main)

makefilePath = VER4 / 'Makefile'
makefile = makefilePath.read_text()
makefile = replaceOnce(
	makefile,
	'SOURCES := solver.cpp preprocess.cpp vivify.cpp main.cpp',
	'SOURCES := solver.cpp preprocess.cpp vivify.cpp branching.cpp main.cpp',
	'branching build source'
)
makefilePath.write_text(makefile)

(VER4 / 'README.md').write_text('''# Uatu Ver. 4

Corrected Ver. 3 with preprocessing, reduction-epoch vivification, and LRB/EVSIDS branching.

## Architecture

- Maintains LRB and canonical EVSIDS scores concurrently and alternates the active heuristic by search-propagation budget without changing the current trail.
- Uses LRB conflict-participation and reason-side rewards with exponential recency updates and locality decay.
- Uses canonical EVSIDS with one bump per conflict participant and a decay factor of 0.95.
- Normalizes clauses and performs bounded unit propagation, subsumption, self-subsuming resolution, and variable elimination before CDCL search.
- Runs bounded clause vivification whenever the learned-clause database is reduced.
- Preserves Uatu's soft rephase and recent-LBD reset behavior; only clause reduction performs `backtrack(0)`.
''')

rootPath = ROOT / 'README.md'
root = rootPath.read_text()
root = replaceOnce(
	root,
	'| `cpu/ver_4` | Corrected Ver. 3 with lightweight preprocessing and model reconstruction |',
	'| `cpu/ver_4` | Corrected Ver. 3 with preprocessing, reduction-epoch vivification, and LRB/EVSIDS branching |',
	'root README version row'
)
rootPath.write_text(root)
