#include "solver.h"
#include "chb.h"
#include "recursive.h"

#include <algorithm>
#include <cstring>


class CHBHeap {
	const double *activity;
	std::vector<int> heap;
	std::vector<int> pos;

	bool compare( int a, int b ) const {
		return activity[a] > activity[b];
	}

	void up( int index ) {
		int variable = heap[index];
		int parent = Parent(index);
		while ( index && compare(variable, heap[parent]) ) {
			heap[index] = heap[parent];
			pos[heap[parent]] = index;
			index = parent;
			parent = Parent(parent);
		}
		heap[index] = variable;
		pos[variable] = index;
	}

	void down( int index ) {
		int variable = heap[index];
		while ( ChildLeft(index) < static_cast<int>(heap.size()) ) {
			const int child = ChildRight(index) < static_cast<int>(heap.size()) &&
				compare(heap[ChildRight(index)], heap[ChildLeft(index)])
				? ChildRight(index) : ChildLeft(index);
			if ( compare(variable, heap[child]) ) break;
			heap[index] = heap[child];
			pos[heap[index]] = index;
			index = child;
		}
		heap[index] = variable;
		pos[variable] = index;
	}

public:
	void initialize( const double *scores, const int8_t *value, int vars ) {
		activity = scores;
		heap.clear();
		pos.assign(vars + 1, -1);
		for ( int variable = 1; variable <= vars; variable ++ ) {
			if ( value[variable] == 0 ) insert(variable);
		}
	}

	bool empty( void ) const {
		return heap.empty();
	}

	bool inHeap( int variable ) const {
		return variable < static_cast<int>(pos.size()) && pos[variable] >= 0;
	}

	void update( int variable ) {
		if ( !inHeap(variable) ) return;
		const int position = pos[variable];
		up(position);
		down(pos[variable]);
	}

	void insert( int variable ) {
		if ( inHeap(variable) ) return;
		if ( static_cast<int>(pos.size()) <= variable ) pos.resize(variable + 1, -1);
		pos[variable] = heap.size();
		heap.push_back(variable);
		up(pos[variable]);
	}

	int pop( void ) {
		const int variable = heap[0];
		const int lastVariable = heap.back();
		heap.pop_back();
		pos[variable] = -1;

		if ( !heap.empty() ) {
			heap[0] = lastVariable;
			pos[lastVariable] = 0;
			down(0);
		}
		return variable;
	}
};


typedef struct CHBState {
	CHBHeap heap;
	std::vector<int> lastConflict;
	int action;
	double step;
	long long scoreUpdates;
}CHBState;


static long long chbScoreUpdatesFinal = 0;


// Elapsed time checker
static inline double timeCheckerCPUCHB( void ) {
	struct rusage ru;
	getrusage(RUSAGE_SELF, &ru);
	return static_cast<double>(ru.ru_utime.tv_sec) +
		static_cast<double>(ru.ru_utime.tv_usec) / 1000000;
}

// Get a literal value
static inline int getLiteralValue( const Solver &solver, int literal ) {
	return literal > 0 ? solver.value[literal] : -solver.value[-literal];
}

// Initialize CHB state
static void initializeCHB( Solver &solver, CHBState &state ) {
	state.lastConflict.assign(solver.vars + 1, 0);
	state.action = 0;
	state.step = 0.4;
	state.scoreUpdates = 0;
	state.heap.initialize(solver.activity, solver.value, solver.vars);
}

// Update a CHB score
static void updateCHBScore( Solver &solver, CHBState &state,
				    int variable, double multiplier ) {
	int age = solver.conflicts - state.lastConflict[variable] + 1;
	if ( age < 1 ) age = 1;

	const double reward = multiplier / static_cast<double>(age);
	solver.activity[variable] = state.step * reward +
		(1.0 - state.step) * solver.activity[variable];
	state.heap.update(variable);
	state.scoreUpdates ++;
}

// Reward variables assigned since the previous propagation event
static void updateAssignedCHB( Solver &solver, CHBState &state, bool conflict ) {
	if ( state.action > static_cast<int>(solver.trail.size()) ) {
		state.action = solver.trail.size();
	}

	const double multiplier = conflict ? 1.0 : 0.9;
	for ( int i = state.action; i < static_cast<int>(solver.trail.size()); i ++ ) {
		updateCHBScore(solver, state, abs(solver.trail[i]), multiplier);
	}
	state.action = solver.trail.size();
}

// Pick a decision variable based on CHB
static int decideCHB( Solver &solver, CHBState &state ) {
	int next = -1;
	while ( next == -1 || getLiteralValue(solver, next) != 0 ) {
		if ( state.heap.empty() ) return 10;
		next = state.heap.pop();
	}

	solver.decVarInTrail.push_back(solver.trail.size());
	if ( solver.saved[next] ) next *= solver.saved[next];
	solver.assign(next, solver.decVarInTrail.size(), -1);
	solver.decides ++;
	return 0;
}

// Backtrack and restore variables to the CHB heap
static void backtrackCHB( Solver &solver, CHBState &state, int backtrackLevel ) {
	if ( static_cast<int>(solver.decVarInTrail.size()) <= backtrackLevel ) return;

	const int trailLimit = solver.decVarInTrail[backtrackLevel];
	for ( int i = static_cast<int>(solver.trail.size()) - 1;
	      i >= trailLimit; i -- ) {
		const int variable = abs(solver.trail[i]);

		solver.saved[variable] = solver.trail[i] > 0 ? 1 : -1;
		solver.value[variable] = 0;
		solver.reason[variable] = -1;
		solver.level[variable] = 0;
		state.heap.insert(variable);
	}

	solver.propagated = trailLimit;
	solver.trail.resize(solver.propagated);
	solver.decVarInTrail.resize(backtrackLevel);
	if ( state.action > solver.propagated ) state.action = solver.propagated;
}

// First-UIP conflict analysis with CHB conflict history updates
static int analyzeCHB( Solver &solver, CHBState &state, int conflict,
		       int &backtrackLevel, int &lbd ) {
	solver.time_stamp ++;
	solver.learnt.clear();

	if ( conflict < 0 || conflict >= static_cast<int>(solver.clauseDB.size()) ) {
		fprintf( stderr, "internal error: invalid conflict clause\n" );
		return 30;
	}

	const int conflictLevel = static_cast<int>(solver.decVarInTrail.size());
	if ( conflictLevel == 0 ) return 20;

	solver.learnt.push_back(0);
	int unresolved = 0;
	int resolveLiteral = 0;
	int trailIndex = static_cast<int>(solver.trail.size()) - 1;

	do {
		if ( conflict < 0 || conflict >= static_cast<int>(solver.clauseDB.size()) ) {
			fprintf( stderr, "internal error: invalid reason clause\n" );
			return 30;
		}

		solver.updateClauseQuality(conflict);
		Clause &clause = solver.clauseDB[conflict];
		const int begin = resolveLiteral == 0 ? 0 : 1;
		for ( int i = begin; i < static_cast<int>(clause.literals.size()); i ++ ) {
			const int variable = abs(clause[i]);
			if ( solver.mark[variable] == solver.time_stamp ||
			     solver.level[variable] == 0 ) continue;

			state.lastConflict[variable] = solver.conflicts;
			solver.mark[variable] = solver.time_stamp;
			if ( solver.level[variable] == conflictLevel ) unresolved ++;
			else solver.learnt.push_back(clause[i]);
		}

		while ( trailIndex >= 0 &&
			solver.mark[abs(solver.trail[trailIndex])] != solver.time_stamp ) {
			trailIndex --;
		}
		if ( trailIndex < 0 ) {
			fprintf( stderr, "internal error: malformed implication graph\n" );
			return 30;
		}

		resolveLiteral = solver.trail[trailIndex --];
		solver.mark[abs(resolveLiteral)] = 0;
		unresolved --;

		if ( unresolved > 0 ) {
			const int nextReason = solver.reason[abs(resolveLiteral)];
			if ( nextReason < 0 ||
			     nextReason >= static_cast<int>(solver.clauseDB.size()) ) {
				fprintf( stderr, "internal error: invalid reason clause\n" );
				return 30;
			}
			conflict = nextReason;
		}
	} while ( unresolved > 0 );

	solver.learnt[0] = -resolveLiteral;

	// Recursive reason-graph minimization
	minimizeLearnedClauseRecursive(solver);

	solver.time_stamp ++;
	lbd = 0;
	for ( int literal : solver.learnt ) {
		const int decisionLevel = solver.level[abs(literal)];
		if ( decisionLevel && solver.mark[decisionLevel] != solver.time_stamp ) {
			solver.mark[decisionLevel] = solver.time_stamp;
			lbd ++;
		}
	}

	if ( solver.lbd_queue_size < 50 ) solver.lbd_queue_size ++;
	else solver.fast_lbd_sum -= solver.lbd_queue[solver.lbd_queue_pos];
	solver.lbd_queue[solver.lbd_queue_pos ++] = lbd;
	if ( solver.lbd_queue_pos == 50 ) solver.lbd_queue_pos = 0;
	solver.fast_lbd_sum += lbd;
	solver.slow_lbd_sum += lbd > 50 ? 50 : lbd;

	if ( solver.learnt.size() == 1 ) {
		backtrackLevel = 0;
	} else {
		int maxIndex = 1;
		for ( int i = 2; i < static_cast<int>(solver.learnt.size()); i ++ ) {
			if ( solver.level[abs(solver.learnt[i])] >
			     solver.level[abs(solver.learnt[maxIndex])] ) maxIndex = i;
		}
		std::swap(solver.learnt[1], solver.learnt[maxIndex]);
		backtrackLevel = solver.level[abs(solver.learnt[1])];
	}

	return 0;
}

// Solve with CHB branching
int solveCHB( Solver &solver ) {
	CHBState state;
	initializeCHB(solver, state);

	int result = 0;
	const double processStart = timeCheckerCPUCHB();
	double timeLimit = 2000.0;
	if ( const char *env = getenv("UATU_TIMEOUT_SEC") ) {
		const double parsed = atof(env);
		if ( parsed > 0.0 ) timeLimit = parsed;
	}

	unsigned long long loopCounter = 0;
	while ( !result ) {
		if ( (loopCounter++ & 4095ULL) == 0 &&
		     timeCheckerCPUCHB() - processStart >= timeLimit ) {
			result = 30;
			break;
		}

		const int conflictClause = solver.propagate();
		updateAssignedCHB(solver, state, conflictClause != -1);
		if ( conflictClause != -1 ) {
			if ( static_cast<int>(solver.trail.size()) > solver.threshold ) {
				solver.threshold = solver.trail.size();
				memcpy(solver.local_best + 1, solver.value + 1,
				       static_cast<size_t>(solver.vars) * sizeof(*solver.value));
			}

			int backtrackLevel = 0;
			int lbd = 0;
			result = analyzeCHB(solver, state, conflictClause, backtrackLevel, lbd);
			if ( result != 0 ) break;

			backtrackCHB(solver, state, backtrackLevel);
			if ( solver.learnt.size() == 1 ) {
				solver.assign(solver.learnt[0], 0, -1);
			} else {
				const int learnedClause = solver.add_clause(solver.learnt);
				solver.clauseDB[learnedClause].lbd = lbd;
				solver.assign(solver.learnt[0], backtrackLevel, learnedClause);
			}

			if ( state.step > 0.06 ) {
				state.step -= 0.000001;
				if ( state.step < 0.06 ) state.step = 0.06;
			}
			solver.clause_inc *= 1.0 / solver.clause_decay;
			solver.conflicts ++;
			solver.reduces ++;
		} else if ( solver.reduces >= solver.reduce_limit ) {
			solver.reduce();
			state.heap.initialize(solver.activity, solver.value, solver.vars);
			state.action = solver.trail.size();
		} else if ( solver.lbd_queue_size == 50 &&
			    0.8 * solver.fast_lbd_sum / solver.lbd_queue_size >
				    solver.slow_lbd_sum / solver.conflicts ) {
			solver.resetRecentLBD();
		} else if ( solver.conflicts >= solver.rephase_limit ) {
			solver.rephase();
		} else {
			result = decideCHB(solver, state);
		}
	}

	solver.processTimeFinal = timeCheckerCPUCHB() - processStart;
	chbScoreUpdatesFinal = state.scoreUpdates;
	printf( "Elapsed Time [Total] (CPU): %.4f\n", solver.processTimeFinal );
#if UATU_PROFILE_BCP
	printf( "Elapsed Time [Propa] (wall): %.4f\n", solver.propagaTimeFinal );
	printf( "Elapsed Time [MaxBCP] (wall): %.4f\n", solver.maxBCPTime );
#endif
	printf( "----------------------------------------------------\n" );
	return result;
}

// Return the number of CHB score updates
long long getCHBScoreUpdates( void ) {
	return chbScoreUpdatesFinal;
}
