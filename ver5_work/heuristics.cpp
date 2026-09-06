#include "solver.h"
#include "heuristics.h"

#include <algorithm>
#include <cstring>


// Each option can be disabled without changing the BCP interface.
static bool optionEnabled( const char *name ) {
	const char *value = getenv(name);
	return value == nullptr || strcmp(value, "0") != 0;
}

void configureHeuristics( Solver &solver ) {
	solver.options.adaptiveEVSIDS = optionEnabled("UATU_ADAPTIVE_EVSIDS");
	solver.options.blockedRestart = optionEnabled("UATU_BLOCKED_RESTART");
	solver.options.lbdReduction = optionEnabled("UATU_LBD_REDUCTION");
	solver.options.recursiveMinimization = optionEnabled("UATU_RECURSIVE_MINIMIZATION");
	solver.options.vivification = optionEnabled("UATU_VIVIFICATION");
	solver.heuristics.minimizeStack.reserve(64);
	solver.heuristics.minimizeTouched.reserve(64);
}

// Observe the conflict before its trail is shortened by analysis/backtracking.
void recordSearchConflict( Solver &solver ) {
	HeuristicState &state = solver.heuristics;
	const uint64_t nextConflict = solver.conflicts == UINT64_MAX
		? UINT64_MAX : solver.conflicts + 1;
	if ( solver.options.adaptiveEVSIDS &&
	     nextConflict % UATU_DECAY_INTERVAL == 0 && solver.var_decay < 0.95 ) {
		solver.var_decay = std::min(0.95, solver.var_decay + 0.01);
		state.decayUpdates ++;
	}

	if ( !solver.options.blockedRestart ) return;
	const int length = static_cast<int>(solver.trail.size());
	if ( state.trailCount == UATU_TRAIL_WINDOW ) {
		state.trailSum -= static_cast<uint64_t>(state.trailHistory[state.trailPosition]);
	} else {
		state.trailCount ++;
	}
	state.trailHistory[state.trailPosition] = length;
	state.trailSum += static_cast<uint64_t>(length);
	state.trailPosition ++;
	if ( state.trailPosition == UATU_TRAIL_WINDOW ) state.trailPosition = 0;

	const double average = static_cast<double>(state.trailSum) / state.trailCount;
	if ( nextConflict > UATU_BLOCK_AFTER && solver.lbd_queue_size == 50 &&
	     static_cast<double>(length) > 1.4 * average ) {
		solver.fast_lbd_sum = 0;
		solver.lbd_queue_size = 0;
		solver.lbd_queue_pos = 0;
		state.blockedRestarts ++;
	}
}

// Traverse a reason closure iteratively and cache only completed successful proofs.
static bool redundantLiteral( Solver &solver, int variable,
			      uint32_t membershipStamp, uint32_t abstractLevels,
			      bool &invalidReason ) {
	if ( solver.reason[variable] == -1 ) return false;
	if ( solver.reason[variable] < 0 ||
	     solver.reason[variable] >= static_cast<int>(solver.clauseDB.size()) ) {
		invalidReason = true;
		return false;
	}

	HeuristicState &state = solver.heuristics;
	state.minimizeStack.clear();
	state.minimizeTouched.clear();
	state.minimizeStack.push_back(variable);
	bool redundant = true;
	while ( redundant && !state.minimizeStack.empty() ) {
		const int current = state.minimizeStack.back();
		state.minimizeStack.pop_back();
		const int reference = solver.reason[current];
		if ( reference < 0 || reference >= static_cast<int>(solver.clauseDB.size()) ) {
			invalidReason = true;
			redundant = false;
			break;
		}
		const Clause &reasonClause = solver.clauseDB[reference];
		for ( int literal : reasonClause.literals ) {
			state.recursiveVisits ++;
			const int antecedent = abs(literal);
			if ( antecedent == current || solver.level[antecedent] == 0 ||
			     solver.mark[antecedent] == membershipStamp ) continue;
			const int nextReason = solver.reason[antecedent];
			if ( nextReason == -1 ||
			     (abstractLevels & (uint32_t(1) << (solver.level[antecedent] & 31))) == 0 ) {
				redundant = false;
				break;
			}
			if ( nextReason < 0 || nextReason >= static_cast<int>(solver.clauseDB.size()) ) {
				invalidReason = true;
				redundant = false;
				break;
			}
			solver.mark[antecedent] = membershipStamp;
			state.minimizeTouched.push_back(antecedent);
			state.minimizeStack.push_back(antecedent);
		}
	}

	if ( !redundant ) {
		for ( int touched : state.minimizeTouched ) solver.mark[touched] = 0;
	}
	return redundant;
}

bool minimizeLearntRecursive( Solver &solver ) {
	if ( solver.learnt.size() <= 1 ) return true;
	solver.heuristics.recursiveCalls ++;
	solver.nextAnalysisStamp();
	const uint32_t membershipStamp = solver.time_stamp;
	uint32_t abstractLevels = 0;
	for ( int literal : solver.learnt ) {
		const int variable = abs(literal);
		solver.mark[variable] = membershipStamp;
		abstractLevels |= uint32_t(1) << (solver.level[variable] & 31);
	}

	int out = 1;
	for ( int i = 1; i < static_cast<int>(solver.learnt.size()); i ++ ) {
		const int literal = solver.learnt[i];
		bool invalidReason = false;
		const bool removable = redundantLiteral(
			solver, abs(literal), membershipStamp, abstractLevels, invalidReason
		);
		if ( invalidReason ) {
			fprintf( stderr, "internal error: invalid recursive-minimization reason\n" );
			return false;
		}
		if ( removable ) {
			solver.minimizedLiterals ++;
			solver.heuristics.recursiveRemoved ++;
		} else {
			solver.learnt[out ++] = literal;
		}
	}
	solver.learnt.resize(out);
	return true;
}
