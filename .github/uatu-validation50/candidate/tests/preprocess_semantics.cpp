#include "solver.h"
#include <cassert>
#include <inttypes.h>
#include <string>


static bool satisfiesClause( const std::vector<int> &clause, unsigned mask ) {
	for ( int literal : clause ) {
		const bool positive = (mask & (1U << (abs(literal) - 1))) != 0;
		if ( positive == (literal > 0) ) return true;
	}
	return false;
}


static bool satisfiesFormula( const std::vector<std::vector<int>> &formula, unsigned mask ) {
	for ( const std::vector<int> &clause : formula ) {
		if ( !satisfiesClause(clause, mask) ) return false;
	}
	return true;
}


static void checkReferences( const Solver &s ) {
	std::vector<int> watchCount(s.clauseDB.size(), 0);
	for ( int literal = -s.vars; literal <= s.vars; literal ++ ) {
		if ( literal == 0 ) continue;
		for ( const WL &watch : s.watched_literals[s.vars + literal] ) {
			assert(watch.clauseIdx >= 0 && watch.clauseIdx < static_cast<int>(s.clauseDB.size()));
			const Clause &clause = s.clauseDB[watch.clauseIdx];
			assert(clause.literals.size() >= 2);
			assert(clause.literals[0] == -literal || clause.literals[1] == -literal);
			bool blockerFound = false;
			for ( int member : clause.literals ) {
				if ( member == watch.blocker ) blockerFound = true;
			}
			assert(blockerFound);
			watchCount[watch.clauseIdx] ++;
		}
	}
	for ( int count : watchCount ) assert(count == 2);
	for ( int literal : s.trail ) {
		assert(s.value[abs(literal)] == (literal > 0 ? 1 : -1));
		const int reason = s.reason[abs(literal)];
		if ( reason == -1 ) continue;
		assert(reason >= 0 && reason < static_cast<int>(s.clauseDB.size()));
		bool found = false;
		for ( int member : s.clauseDB[reason].literals ) {
			if ( member == literal ) found = true;
		}
		assert(found);
	}
}


int main( int argc, char **argv ) {
	assert(argc == 2);
	FILE *file = fopen(argv[1], "r");
	assert(file);
	int variables = 0;
	int clauses = 0;
	assert(fscanf(file, "p cnf %d %d", &variables, &clauses) == 2);
	assert(variables >= 0 && variables <= 12);
	std::vector<std::vector<int>> formula;
	for ( int index = 0; index < clauses; index ++ ) {
		std::vector<int> clause;
		int literal = 0;
		do {
			assert(fscanf(file, "%d", &literal) == 1);
			if ( literal != 0 ) clause.push_back(literal);
		} while ( literal != 0 );
		formula.push_back(clause);
	}
	fclose(file);
	std::vector<unsigned> originalModels;
	for ( unsigned mask = 0; mask < (1U << variables); mask ++ ) {
		if ( satisfiesFormula(formula, mask) ) originalModels.push_back(mask);
	}
	Solver solver{};
	int result = solver.parse(argv[1]);
	if ( result == 0 ) result = solver.preprocess();
	assert(result == 0 || result == 20);
	uint64_t extensions = 0;
	if ( result == 20 ) {
		assert(originalModels.empty());
	} else {
		checkReferences(solver);
		std::vector<int> roots(variables + 1, 0);
		unsigned activeMask = 0;
		for ( int variable = 1; variable <= variables; variable ++ ) {
			roots[variable] = solver.value[variable];
			if ( !solver.eliminated[variable] ) activeMask |= 1U << (variable - 1);
		}
		std::vector<bool> originalProjection(1U << variables, false);
		for ( unsigned mask : originalModels ) {
			originalProjection[mask & activeMask] = true;
			for ( int variable = 1; variable <= variables; variable ++ ) {
				if ( roots[variable] != 0 ) {
					assert(roots[variable] == ((mask & (1U << (variable - 1))) ? 1 : -1));
				}
			}
			for ( const Clause &clause : solver.clauseDB ) assert(satisfiesClause(clause.literals, mask));
		}
		for ( unsigned mask = 0; mask < (1U << variables); mask ++ ) {
			bool reducedModel = true;
			for ( int variable = 1; variable <= variables; variable ++ ) {
				const int value = (mask & (1U << (variable - 1))) ? 1 : -1;
				if ( roots[variable] != 0 && roots[variable] != value ) reducedModel = false;
			}
			for ( const Clause &clause : solver.clauseDB ) {
				for ( int literal : clause.literals ) assert(!solver.eliminated[abs(literal)]);
				if ( !satisfiesClause(clause.literals, mask) ) reducedModel = false;
			}
			if ( !reducedModel ) continue;
			assert(originalProjection[mask & activeMask]);
			for ( int variable = 1; variable <= variables; variable ++ ) {
				solver.value[variable] = solver.eliminated[variable] ? 0 :
					((mask & (1U << (variable - 1))) ? 1 : -1);
			}
			solver.extendModel();
			unsigned extendedMask = 0;
			for ( int variable = 1; variable <= variables; variable ++ ) {
				assert(solver.value[variable] == 1 || solver.value[variable] == -1);
				if ( !solver.eliminated[variable] ) {
					assert(solver.value[variable] == ((mask & (1U << (variable - 1))) ? 1 : -1));
				}
				if ( solver.value[variable] == 1 ) extendedMask |= 1U << (variable - 1);
			}
			assert(satisfiesFormula(formula, extendedMask));
			extensions ++;
		}
		assert((extensions != 0) == !originalModels.empty());
	}
	printf( "{\"original_models\":%zu,\"extensions\":%" PRIu64 ","
		"\"eliminated\":%" PRIu64 ",\"subsumed\":%" PRIu64 ","
		"\"strengthened\":%" PRIu64 ",\"resolvents\":%" PRIu64 ",\"work\":%" PRIu64 "}\n",
		originalModels.size(), extensions, solver.preprocessingEliminated,
		solver.preprocessingSubsumed, solver.preprocessingStrengthened,
		solver.preprocessingResolvents, solver.preprocessingWork );
	return 0;
}
