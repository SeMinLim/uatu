#include "solver.h"
#include <algorithm>


static constexpr size_t VIVIFY_MAX_CANDIDATES = 64;
static constexpr size_t VIVIFY_MAX_SIZE = 30;
static constexpr int VIVIFY_MAX_LBD = 6;
static constexpr int VIVIFY_MAX_SCAN = 4096;
static constexpr uint64_t VIVIFY_MAX_WORK = 200000;


struct VivifyCandidate {
	int clauseIdx;
	int lbd;
	size_t size;
	double activity;
};

static bool betterVivifyCandidate( const VivifyCandidate &a,
                                   const VivifyCandidate &b ) {
	if ( a.lbd != b.lbd ) return a.lbd < b.lbd;
	if ( a.activity != b.activity ) return a.activity > b.activity;
	if ( a.size != b.size ) return a.size < b.size;
	return a.clauseIdx > b.clauseIdx;
}

static void removeVivifyWatch( std::vector<WL> &watchers, int clauseIdx ) {
	size_t out = 0;
	for ( size_t i = 0; i < watchers.size(); i ++ ) {
		if ( watchers[i].clauseIdx != clauseIdx ) watchers[out ++] = watchers[i];
	}
	watchers.resize(out);
}

// Temporary assumptions must not replace the search's saved phases.
static void undoVivifyAssumptions( Solver &solver, int rootSize ) {
	for ( int i = static_cast<int>(solver.trail.size()) - 1; i >= rootSize; i -- ) {
		const int variable = abs(solver.trail[i]);
		solver.value[variable] = 0;
		solver.reason[variable] = -1;
		solver.level[variable] = 0;
	}
	solver.trail.resize(rootSize);
	solver.propagated = rootSize;
	solver.decVarInTrail.clear();
}

// Shorten selected learnt clauses with root-level, budgeted unit propagation.
int Solver::vivifyLearnts() {
	if ( !decVarInTrail.empty() ) return 0;
	if ( propagate() != -1 ) return 20;
	vivificationRuns ++;

	const int end = static_cast<int>(clauseDB.size());
	const int begin = std::max(origin_clauses, end - VIVIFY_MAX_SCAN);
	std::vector<VivifyCandidate> candidates;
	candidates.reserve(std::min(VIVIFY_MAX_SCAN, end - begin));
	for ( int cref = begin; cref < end; cref ++ ) {
		const Clause &clause = clauseDB[cref];
		if ( clause.literals.size() < 3 || clause.literals.size() > VIVIFY_MAX_SIZE ||
		     clause.lbd > VIVIFY_MAX_LBD ) continue;
		bool satisfied = false;
		for ( int literal : clause.literals ) {
			if ( Value(literal) == 1 ) {
				satisfied = true;
				break;
			}
		}
		// Every root reason contains its true implied literal and stays attached.
		if ( !satisfied ) {
			candidates.push_back({cref, clause.lbd, clause.literals.size(), clause.activity});
		}
	}
	std::sort(candidates.begin(), candidates.end(), betterVivifyCandidate);
	if ( candidates.size() > VIVIFY_MAX_CANDIDATES ) candidates.resize(VIVIFY_MAX_CANDIDATES);

	uint64_t workBudget = VIVIFY_MAX_WORK;
	std::vector<int> original;
	std::vector<int> shortened;
	original.reserve(VIVIFY_MAX_SIZE);
	shortened.reserve(VIVIFY_MAX_SIZE);
	for ( const VivifyCandidate &candidate : candidates ) {
		const int cref = candidate.clauseIdx;
		Clause &clause = clauseDB[cref];
		bool satisfied = false;
		for ( int literal : clause.literals ) {
			if ( Value(literal) == 1 ) {
				satisfied = true;
				break;
			}
		}
		if ( satisfied ) continue;

		const int firstWatch = clause[0];
		const int secondWatch = clause[1];
		uint64_t detachWork = WatchedLiterals(-firstWatch).size();
		if ( firstWatch != secondWatch ) detachWork += WatchedLiterals(-secondWatch).size();
		if ( workBudget <= detachWork ) {
			vivificationBudgetStops ++;
			break;
		}
		workBudget -= detachWork;
		vivificationCandidates ++;
		original = clause.literals;
		shortened.clear();
		removeVivifyWatch(WatchedLiterals(-firstWatch), cref);
		if ( firstWatch != secondWatch ) removeVivifyWatch(WatchedLiterals(-secondWatch), cref);

		// The target cannot imply a literal or cause a conflict during its own probe.
		const int rootSize = static_cast<int>(trail.size());
		decVarInTrail.push_back(rootSize);
		bool interrupted = false;
		for ( int literal : original ) {
			if ( workBudget == 0 ) {
				interrupted = true;
				break;
			}
			workBudget --;
			if ( Value(literal) == -1 ) continue;
			shortened.push_back(literal);
			if ( Value(literal) == 1 ) break;

			assign(-literal, 1, -1);
			const int conflictClause = propagate(&workBudget);
			if ( conflictClause == -2 ) {
				interrupted = true;
				break;
			}
			if ( conflictClause >= 0 ) break;
		}
		undoVivifyAssumptions(*this, rootSize);

		if ( !interrupted && shortened.size() < original.size() ) {
			vivifiedClauses ++;
			vivifiedLiterals += original.size() - shortened.size();
			if ( shortened.size() >= 2 ) {
				clause.literals = shortened;
				clause.lbd = std::min(clause.lbd, static_cast<int>(shortened.size()));
				clause.canBeDeleted = false;
			}
		}
		WatchedLiterals(-clause[0]).push_back(WL(cref, clause[1]));
		WatchedLiterals(-clause[1]).push_back(WL(cref, clause[0]));

		if ( interrupted ) {
			vivificationBudgetStops ++;
			break;
		}
		if ( shortened.empty() ) return 20;
		if ( shortened.size() == 1 ) {
			// Unit clauses live on the permanent root trail; keep the old clause satisfied.
			const int literal = shortened[0];
			if ( Value(literal) == -1 ) return 20;
			if ( Value(literal) == 0 ) assign(literal, 0, -1);
			// This is mandatory root propagation, outside the speculative-work budget.
			if ( propagate() != -1 ) return 20;
		}
	}
	return 0;
}
