#include "solver.h"
#include "recursive.h"

#include <algorithm>
#include <climits>
#include <cstring>


typedef struct MinimizeFrame {
	int variable;
	size_t nextLiteral;
}MinimizeFrame;


// Elapsed time checker
static inline double timeCheckerCPURecursive( void ) {
	struct rusage ru;
	getrusage(RUSAGE_SELF, &ru);
	return static_cast<double>(ru.ru_utime.tv_sec) +
		static_cast<double>(ru.ru_utime.tv_usec) / 1000000;
}

// Check whether a reason closure is redundant
static bool recursivelyRedundant( Solver &solver,
				  int rootVariable,
				  int membershipStamp,
				  unsigned int visitingStamp,
				  unsigned int redundantStamp,
				  std::vector<MinimizeFrame> &recursionStack,
				  std::vector<int> &recursionTouched ) {
	if ( solver.lbdMark[rootVariable] == redundantStamp ) return true;
	if ( solver.reason[rootVariable] < 0 ) return false;

	recursionStack.clear();
	recursionTouched.clear();
	recursionStack.push_back({rootVariable, 0});

	while ( !recursionStack.empty() ) {
		MinimizeFrame &frame = recursionStack.back();
		const int variable = frame.variable;

		if ( solver.lbdMark[variable] == redundantStamp ) {
			recursionStack.pop_back();
			continue;
		}

		if ( frame.nextLiteral == 0 &&
		     solver.lbdMark[variable] != visitingStamp ) {
			solver.lbdMark[variable] = visitingStamp;
			recursionTouched.push_back(variable);
		}

		const int reasonClause = solver.reason[variable];
		if ( reasonClause < 0 ) {
			for ( int touched : recursionTouched ) {
				if ( solver.lbdMark[touched] == visitingStamp ) {
					solver.lbdMark[touched] = 0;
				}
			}
			return false;
		}

		const Clause &reasonData = solver.clauseDB[reasonClause];
		bool descended = false;
		while ( frame.nextLiteral < reasonData.literals.size() ) {
			const int qvar = abs(reasonData.literals[frame.nextLiteral ++]);
			if ( qvar == variable || solver.level[qvar] == 0 ) continue;
			if ( solver.mark[qvar] == membershipStamp ) continue;
			if ( solver.lbdMark[qvar] == redundantStamp ) continue;

			if ( solver.reason[qvar] < 0 ||
			     solver.lbdMark[qvar] == visitingStamp ) {
				for ( int touched : recursionTouched ) {
					if ( solver.lbdMark[touched] == visitingStamp ) {
						solver.lbdMark[touched] = 0;
					}
				}
				return false;
			}

			recursionStack.push_back({qvar, 0});
			descended = true;
			break;
		}

		if ( descended ) continue;

		solver.lbdMark[variable] = redundantStamp;
		recursionStack.pop_back();
	}

	return true;
}

// First-UIP conflict analysis with recursive minimization
static int analyzeRecursive( Solver &solver, int conflict,
			     int &backtrackLevel, int &lbd ) {
	solver.time_stamp ++;
	solver.learnt.clear();

	const int conflictLevel = solver.level[abs(solver.clauseDB[conflict][0])];
	if ( conflictLevel == 0 ) return 20;

	solver.learnt.push_back(0);
	int unresolved = 0;
	int resolveLiteral = 0;
	int trailIndex = static_cast<int>(solver.trail.size()) - 1;
	std::vector<int> bump;
	bump.reserve(32);

	do {
		solver.updateClauseQuality(conflict);
		Clause &clause = solver.clauseDB[conflict];
		const int begin = resolveLiteral == 0 ? 0 : 1;
		for ( int i = begin; i < static_cast<int>(clause.literals.size()); i ++ ) {
			const int variable = abs(clause[i]);
			if ( solver.mark[variable] == solver.time_stamp ||
			     solver.level[variable] == 0 ) continue;

			solver.update_score(variable, 0.5);
			bump.push_back(variable);
			solver.mark[variable] = solver.time_stamp;

			if ( solver.level[variable] >= conflictLevel ) unresolved ++;
			else solver.learnt.push_back(clause[i]);
		}

		while ( trailIndex >= 0 &&
			solver.mark[abs(solver.trail[trailIndex])] != solver.time_stamp ) {
			trailIndex --;
		}
		if ( trailIndex < 0 ) {
			fprintf( stderr, "internal error: malformed implication graph\n" );
			abort();
		}

		resolveLiteral = solver.trail[trailIndex --];
		conflict = solver.reason[abs(resolveLiteral)];
		solver.mark[abs(resolveLiteral)] = 0;
		unresolved --;
	} while ( unresolved > 0 );

	solver.learnt[0] = -resolveLiteral;

	// Recursive reason-graph minimization
	if ( solver.learnt.size() > 1 ) {
		solver.time_stamp ++;
		const int membershipStamp = solver.time_stamp;
		for ( int literal : solver.learnt ) {
			solver.mark[abs(literal)] = membershipStamp;
		}

		if ( solver.lbdStamp >= UINT_MAX - 2 ) {
			for ( int i = 0; i <= solver.vars; i ++ ) solver.lbdMark[i] = 0;
			solver.lbdStamp = 0;
		}
		const unsigned int visitingStamp = ++solver.lbdStamp;
		const unsigned int redundantStamp = ++solver.lbdStamp;

		std::vector<MinimizeFrame> recursionStack;
		std::vector<int> recursionTouched;
		recursionStack.reserve(32);
		recursionTouched.reserve(32);

		int out = 1;
		for ( int i = 1; i < static_cast<int>(solver.learnt.size()); i ++ ) {
			const int literal = solver.learnt[i];
			const int variable = abs(literal);
			const bool removable = recursivelyRedundant(
				solver,
				variable,
				membershipStamp,
				visitingStamp,
				redundantStamp,
				recursionStack,
				recursionTouched
			);

			if ( removable ) solver.minimizedLiterals ++;
			else solver.learnt[out ++] = literal;
		}
		solver.learnt.resize(out);
	}

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

	for ( int variable : bump ) {
		if ( solver.level[variable] >= backtrackLevel - 1 ) {
			solver.update_score(variable, 1.0);
		}
	}

	return 0;
}

// Solve with recursive learned-clause minimization
int solveRecursive( Solver &solver ) {
	int result = 0;
	const double processStart = timeCheckerCPURecursive();
	double timeLimit = 2000.0;
	if ( const char *env = getenv("UATU_TIMEOUT_SEC") ) {
		const double parsed = atof(env);
		if ( parsed > 0.0 ) timeLimit = parsed;
	}

	unsigned long long loopCounter = 0;
	while ( !result ) {
		if ( (loopCounter ++ & 4095ULL) == 0 &&
		     timeCheckerCPURecursive() - processStart >= timeLimit ) {
			result = 30;
			break;
		}

		const int conflictClause = solver.propagate();
		if ( conflictClause != -1 ) {
			if ( static_cast<int>(solver.trail.size()) > solver.threshold ) {
				solver.threshold = solver.trail.size();
				memcpy(solver.local_best + 1, solver.value + 1,
				       static_cast<size_t>(solver.vars) * sizeof(*solver.value));
			}

			int backtrackLevel = 0;
			int lbd = 0;
			result = analyzeRecursive(solver, conflictClause, backtrackLevel, lbd);
			if ( result == 20 ) break;

			solver.backtrack(backtrackLevel);
			if ( solver.learnt.size() == 1 ) {
				solver.assign(solver.learnt[0], 0, -1);
			} else {
				const int learnedClause = solver.add_clause(solver.learnt);
				solver.clauseDB[learnedClause].lbd = lbd;
				solver.assign(solver.learnt[0], backtrackLevel, learnedClause);
			}

			solver.var_inc *= 1.0 / solver.var_decay;
			solver.clause_inc *= 1.0 / solver.clause_decay;
			solver.conflicts ++;
			solver.reduces ++;
		} else if ( solver.reduces >= solver.reduce_limit ) {
			solver.reduce();
		} else if ( solver.lbd_queue_size == 50 &&
			    0.8 * solver.fast_lbd_sum / solver.lbd_queue_size >
				    solver.slow_lbd_sum / solver.conflicts ) {
			solver.resetRecentLBD();
		} else if ( solver.conflicts >= solver.rephase_limit ) {
			solver.rephase();
		} else {
			result = solver.decide();
		}
	}

	solver.processTimeFinal = timeCheckerCPURecursive() - processStart;
	printf( "Elapsed Time [Total] (CPU): %.4f\n", solver.processTimeFinal );
#if UATU_PROFILE_BCP
	printf( "Elapsed Time [Propa] (wall): %.4f\n", solver.propagaTimeFinal );
	printf( "Elapsed Time [MaxBCP] (wall): %.4f\n", solver.maxBCPTime );
#endif
	printf( "----------------------------------------------------\n" );
	return result;
}
