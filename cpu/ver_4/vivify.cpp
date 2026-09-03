#include "solver.h"

#include <algorithm>
#include <climits>
#include <cstdlib>
#include <vector>


#define VIVIFY_DEFAULT_MAX_CANDIDATES 32
#define VIVIFY_DEFAULT_MAX_CLAUSE_SIZE 32
#define VIVIFY_DEFAULT_MAX_LEARNT_LBD 6
#define VIVIFY_DEFAULT_MAX_ASSIGNMENTS 50000


typedef struct VivificationCandidate {
	int clause;
	int size;
	int lbd;
	bool learnt;
	uint32_t useCount;
	double activity;
}VivificationCandidate;


// Read a positive integer configuration value
static int readPositiveOption( const char *name, int defaultValue ) {
	const char *environment = getenv(name);
	if ( environment == NULL ) return defaultValue;

	char *end = NULL;
	const long parsed = strtol(environment, &end, 10);
	if ( end == environment || *end != '\0' || parsed <= 0 || parsed > INT_MAX ) {
		return defaultValue;
	}
	return static_cast<int>(parsed);
}

// Read a Boolean configuration value
static bool readBooleanOption( const char *name, bool defaultValue ) {
	const char *environment = getenv(name);
	if ( environment == NULL ) return defaultValue;
	return atoi(environment) != 0;
}

// Order learnt clauses before original clauses, then prioritize useful clauses
static bool vivificationCandidateLess( const VivificationCandidate &left,
				       const VivificationCandidate &right ) {
	if ( left.learnt != right.learnt ) return left.learnt > right.learnt;
	if ( left.learnt && left.lbd != right.lbd ) return left.lbd < right.lbd;
	if ( left.useCount != right.useCount ) return left.useCount > right.useCount;
	if ( left.activity != right.activity ) return left.activity > right.activity;
	if ( left.size != right.size ) return left.size < right.size;
	return left.clause < right.clause;
}

// Remove one clause from a watched-literal list
static void removeClauseWatcher( std::vector<WL> &watchers, int cref ) {
	int out = 0;
	for ( int i = 0; i < static_cast<int>(watchers.size()); i ++ ) {
		if ( watchers[i].clauseIdx == cref ) continue;
		if ( out != i ) watchers[out] = watchers[i];
		out ++;
	}
	watchers.resize(out);
}

// Detach a clause from both watched-literal lists
void Solver::detachClause( int cref ) {
	if ( cref < 0 || cref >= static_cast<int>(clauseDB.size()) ) return;
	Clause &clause = clauseDB[cref];
	if ( clause.literals.size() < 2 ) return;

	const int first = clause[0];
	const int second = clause[1];
	removeClauseWatcher(WatchedLiterals(-first), cref);
	if ( second != first ) removeClauseWatcher(WatchedLiterals(-second), cref);
}

// Attach a clause to both watched-literal lists
void Solver::attachClause( int cref ) {
	if ( cref < 0 || cref >= static_cast<int>(clauseDB.size()) ) return;
	Clause &clause = clauseDB[cref];
	if ( clause.literals.size() < 2 ) return;

	WatchedLiterals(-clause[0]).push_back(WL(cref, clause[1]));
	WatchedLiterals(-clause[1]).push_back(WL(cref, clause[0]));
}

// Restore the decision-level-zero state without changing saved phases
void Solver::restoreVivificationTrail( int trailSize ) {
	for ( int i = static_cast<int>(trail.size()) - 1; i >= trailSize; i -- ) {
		const int variable = abs(trail[i]);
		value[variable] = 0;
		reason[variable] = -1;
		level[variable] = 0;
	}

	trail.resize(trailSize);
	propagated = trailSize;
	decVarInTrail.clear();
}

// Vivify bounded original and retained learnt clauses at a reduction epoch
int Solver::vivifyReductionEpoch() {
	if ( !readBooleanOption("UATU_ENABLE_VIVIFY", true) ) return 0;
	if ( !decVarInTrail.empty() || propagated != static_cast<int>(trail.size()) ) {
		fprintf( stderr, "internal error: invalid root state before vivification\n" );
		return 30;
	}

	vivificationRuns ++;
	const int maxCandidates = readPositiveOption(
		"UATU_VIVIFY_MAX_CANDIDATES",
		VIVIFY_DEFAULT_MAX_CANDIDATES
	);
	const int maxClauseSize = readPositiveOption(
		"UATU_VIVIFY_MAX_CLAUSE_SIZE",
		VIVIFY_DEFAULT_MAX_CLAUSE_SIZE
	);
	const int maxLearntLBD = readPositiveOption(
		"UATU_VIVIFY_MAX_LEARNT_LBD",
		VIVIFY_DEFAULT_MAX_LEARNT_LBD
	);
	const int maxAssignments = readPositiveOption(
		"UATU_VIVIFY_MAX_ASSIGNMENTS",
		VIVIFY_DEFAULT_MAX_ASSIGNMENTS
	);

	std::vector<unsigned char> locked(clauseDB.size(), 0);
	for ( int literal : trail ) {
		const int cref = reason[abs(literal)];
		if ( cref >= 0 && cref < static_cast<int>(clauseDB.size()) ) locked[cref] = 1;
	}

	std::vector<VivificationCandidate> candidates;
	for ( int cref = 0; cref < static_cast<int>(clauseDB.size()); cref ++ ) {
		Clause &clause = clauseDB[cref];
		const int size = static_cast<int>(clause.literals.size());
		if ( locked[cref] || clause.vivified || size < 3 || size > maxClauseSize ) {
			continue;
		}

		const bool learntClause = cref >= origin_clauses;
		if ( learntClause && (clause.lbd <= 0 || clause.lbd > maxLearntLBD) ) {
			continue;
		}

		bool rootUnassigned = true;
		for ( int literal : clause.literals ) {
			if ( Value(literal) != 0 ) {
				rootUnassigned = false;
				break;
			}
		}
		if ( !rootUnassigned ) continue;

		VivificationCandidate candidate;
		candidate.clause = cref;
		candidate.size = size;
		candidate.lbd = clause.lbd;
		candidate.learnt = learntClause;
		candidate.useCount = clause.useCount;
		candidate.activity = clause.activity;
		candidates.push_back(candidate);
	}

	std::sort(candidates.begin(), candidates.end(), vivificationCandidateLess);
	if ( static_cast<int>(candidates.size()) > maxCandidates ) {
		candidates.resize(maxCandidates);
	}

	for ( const VivificationCandidate &candidate : candidates ) {
		const int cref = candidate.clause;
		if ( cref < 0 || cref >= static_cast<int>(clauseDB.size()) ) continue;

		Clause &clause = clauseDB[cref];
		if ( clause.vivified || clause.literals.size() < 3 ) continue;

		bool rootUnassigned = true;
		for ( int literal : clause.literals ) {
			if ( Value(literal) != 0 ) {
				rootUnassigned = false;
				break;
			}
		}
		if ( !rootUnassigned ) continue;

		clause.vivified = true;
		vivificationCandidates ++;
		const std::vector<int> original = clause.literals;
		std::vector<int> strengthened;
		strengthened.reserve(original.size());

		detachClause(cref);
		const int rootTrailSize = static_cast<int>(trail.size());
		vivificationActive = true;

		for ( int i = 0; i < static_cast<int>(original.size()); i ++ ) {
			const int literal = original[i];
			const int literalValue = Value(literal);

			if ( literalValue > 0 ) {
				strengthened.push_back(literal);
				break;
			}
			if ( literalValue < 0 ) continue;

			strengthened.push_back(literal);
			decVarInTrail.push_back(trail.size());
			assign(-literal, static_cast<int>(decVarInTrail.size()), -1);

			const int conflict = propagate();
			if ( conflict != -1 ) break;

			if ( static_cast<int>(trail.size()) - rootTrailSize >= maxAssignments ) {
				for ( int j = i + 1; j < static_cast<int>(original.size()); j ++ ) {
					strengthened.push_back(original[j]);
				}
				break;
			}
		}

		vivificationActive = false;
		restoreVivificationTrail(rootTrailSize);

		if ( strengthened.size() >= original.size() ) {
			attachClause(cref);
			continue;
		}

		vivifiedClauses ++;
		vivifiedLiterals += static_cast<long long>(
			original.size() - strengthened.size()
		);

		if ( strengthened.empty() ) {
			clause.literals = original;
			attachClause(cref);
			return 20;
		}

		if ( strengthened.size() == 1 ) {
			clause.literals = original;
			attachClause(cref);

			const int unit = strengthened[0];
			if ( Value(unit) < 0 ) return 20;
			if ( Value(unit) == 0 ) {
				assign(unit, 0, -1);
				vivificationUnits ++;
				if ( propagate() != -1 ) return 20;
			}
			continue;
		}

		clause.literals.swap(strengthened);
		if ( clause.lbd > static_cast<int>(clause.literals.size()) ) {
			clause.lbd = static_cast<int>(clause.literals.size());
		}
		attachClause(cref);
	}

	return 0;
}
