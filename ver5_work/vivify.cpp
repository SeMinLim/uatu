#include "solver.h"
#include "heuristics.h"

#include <algorithm>


static int literalValue( const Solver &solver, int literal ) {
	return literal > 0 ? solver.value[literal] : -solver.value[-literal];
}

static void removeWatch( Solver &solver, int literal, int reference ) {
	std::vector<WL> &watchers = solver.watched_literals[solver.vars + literal];
	size_t out = 0;
	for ( size_t i = 0; i < watchers.size(); i ++ ) {
		if ( watchers[i].clauseIdx != reference ) watchers[out ++] = watchers[i];
	}
	watchers.resize(out);
}

static void attachWatch( Solver &solver, int reference ) {
	const Clause &clause = solver.clauseDB[reference];
	if ( clause.literals.size() < 2 ) return;
	const int first = clause.literals[0];
	const int second = clause.literals[1];
	solver.watched_literals[solver.vars - first].push_back(WL(reference, second));
	solver.watched_literals[solver.vars - second].push_back(WL(reference, first));
}

// Probes do not pop heap entries or alter saved phase targets.
static void rollbackProbe( Solver &solver, size_t rootSize ) {
	for ( size_t i = solver.trail.size(); i > rootSize; ) {
		const int variable = abs(solver.trail[--i]);
		solver.value[variable] = 0;
		solver.reason[variable] = -1;
		solver.level[variable] = 0;
	}
	solver.trail.resize(rootSize);
	solver.propagated = static_cast<int>(rootSize);
	solver.decVarInTrail.clear();
}

// At level zero, every locked reason has a true implied literal.
static bool rootSatisfied( const Solver &solver, const Clause &clause ) {
	for ( int literal : clause.literals ) {
		if ( literalValue(solver, literal) == 1 ) return true;
	}
	return false;
}

// Derive a subclause while the original clause is detached from both watches.
static int vivifyClause( Solver &solver, int reference, uint64_t &budget ) {
	Clause &clause = solver.clauseDB[reference];
	if ( rootSatisfied(solver, clause) ) return 0;
	const std::vector<int> original = clause.literals;
	std::vector<int> prefix;
	prefix.reserve(original.size());
	const size_t rootSize = solver.trail.size();
	solver.decVarInTrail.push_back(static_cast<int>(rootSize));
	removeWatch(solver, -original[0], reference);
	removeWatch(solver, -original[1], reference);
	solver.heuristics.vivifyTried ++;
	clause.vivifyEligible = false;

	bool interrupted = false;
	for ( int literal : original ) {
		if ( budget == 0 ) {
			interrupted = true;
			break;
		}
		budget --;
		solver.heuristics.vivifyWork ++;
		const int current = literalValue(solver, literal);
		if ( current == -1 ) continue;
		prefix.push_back(literal);
		if ( current == 1 ) break;
		solver.assign(-literal, 1, -1);
		const int conflict = solver.propagate(&budget);
		if ( conflict == -2 ) {
			interrupted = true;
			break;
		}
		if ( conflict >= 0 ) break;
	}

	rollbackProbe(solver, rootSize);
	if ( interrupted ) {
		solver.heuristics.vivifyBudgetStops ++;
		attachWatch(solver, reference);
		return 0;
	}
	if ( prefix.size() >= original.size() ) {
		attachWatch(solver, reference);
		return 0;
	}
	if ( prefix.empty() ) {
		attachWatch(solver, reference);
		return 20;
	}

	clause.literals = std::move(prefix);
	clause.lbd = std::min(clause.lbd, static_cast<int>(clause.literals.size()));
	clause.protectOnce = true;
	solver.heuristics.vivifiedClauses ++;
	solver.heuristics.vivifiedLiterals += original.size() - clause.literals.size();
	attachWatch(solver, reference);
	if ( clause.literals.size() == 1 ) {
		const int literal = clause.literals[0];
		if ( literalValue(solver, literal) == -1 ) return 20;
		if ( literalValue(solver, literal) == 0 ) solver.assign(literal, 0, reference);
		if ( solver.propagate() >= 0 ) return 20;
	}
	return 0;
}

int vivifyAtRoot( Solver &solver ) {
	if ( !solver.options.vivification ) return 0;
	if ( !solver.decVarInTrail.empty() ) {
		fprintf( stderr, "internal error: vivification requires decision level zero\n" );
		return 30;
	}
	if ( solver.propagate() >= 0 ) return 20;

	HeuristicState &state = solver.heuristics;
	const uint64_t searchDelta = state.searchWork - state.lastVivifyWork;
	state.lastVivifyWork = state.searchWork;
	uint64_t budget = std::min(uint64_t(UATU_VIVIFY_MAX_WORK), searchDelta / 50);
	const size_t originalCount = static_cast<size_t>(solver.origin_clauses);
	const size_t learntCount = solver.clauseDB.size() - originalCount;
	if ( budget == 0 || learntCount == 0 ) return 0;
	state.vivifyRuns ++;

	std::vector<int> candidates;
	candidates.reserve(UATU_VIVIFY_CANDIDATES);
	const size_t scanLimit = std::min(learntCount, size_t(UATU_VIVIFY_SCAN));
	state.vivifyCursor %= learntCount;
	for ( size_t scanned = 0;
	      scanned < scanLimit && candidates.size() < UATU_VIVIFY_CANDIDATES;
	      scanned ++ ) {
		const size_t reference = originalCount + state.vivifyCursor;
		state.vivifyCursor = (state.vivifyCursor + 1) % learntCount;
		const Clause &clause = solver.clauseDB[reference];
		if ( !clause.vivifyEligible || clause.literals.size() < 4 ||
		     clause.literals.size() > UATU_VIVIFY_MAX_SIZE ||
		     clause.lbd < 3 || clause.lbd > UATU_VIVIFY_MAX_LBD ||
		     rootSatisfied(solver, clause) ) continue;
		candidates.push_back(static_cast<int>(reference));
	}
	std::sort(candidates.begin(), candidates.end(), [&]( int left, int right ) {
		const Clause &a = solver.clauseDB[left];
		const Clause &b = solver.clauseDB[right];
		if ( a.lbd != b.lbd ) return a.lbd < b.lbd;
		if ( a.activity != b.activity ) return a.activity > b.activity;
		return left < right;
	});
	for ( int reference : candidates ) {
		if ( budget == 0 ) break;
		const int result = vivifyClause(solver, reference, budget);
		if ( result != 0 ) return result;
	}
	return 0;
}
