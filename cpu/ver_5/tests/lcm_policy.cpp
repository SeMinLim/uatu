#include "solver.h"
#include <cassert>


static int addTestClause( Solver &solver, std::vector<int> literals, int lbd = 0 ) {
	const int clauseIdx = solver.add_clause(literals);
	solver.clauseDB[clauseIdx].learntClause = lbd != 0;
	solver.clauseDB[clauseIdx].lbd = lbd;
	return clauseIdx;
}


static bool satisfies( const std::vector<int> &clause, unsigned assignment ) {
	for ( size_t i = 0; i < clause.size(); i ++ ) {
		const bool positive = (assignment & (1U << (abs(clause[i]) - 1))) != 0;
		if ( positive == (clause[i] > 0) ) return true;
	}
	return false;
}


static void checkModels( const Solver &solver, const std::vector<Clause> &before,
	const std::vector<int> &rootsBefore ) {
	for ( unsigned assignment = 0; assignment < (1U << solver.vars); assignment ++ ) {
		bool oldModel = true;
		bool newModel = true;
		for ( size_t i = 0; i < before.size(); i ++ ) {
			if ( !satisfies(before[i].literals, assignment) ) oldModel = false;
		}
		for ( size_t i = 0; i < rootsBefore.size(); i ++ ) {
			if ( !satisfies({rootsBefore[i]}, assignment) ) oldModel = false;
		}
		for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
			if ( !satisfies(solver.clauseDB[i].literals, assignment) ) newModel = false;
		}
		for ( size_t i = 0; i < solver.trail.size(); i ++ ) {
			if ( !satisfies({solver.trail[i]}, assignment) ) newModel = false;
		}
		assert(oldModel == newModel);
	}
}


static void checkRootState( const Solver &solver ) {
	assert(solver.decVarInTrail.empty());
	assert(solver.propagated == static_cast<int>(solver.trail.size()));
	for ( int variable = 1; variable <= solver.vars; variable ++ ) {
		assert(solver.level[variable] == 0);
		if ( solver.value[variable] == 0 ) assert(solver.reason[variable] == -1);
		if ( solver.reason[variable] >= 0 ) {
			assert(static_cast<size_t>(solver.reason[variable]) < solver.clauseDB.size());
		}
	}
}


int main() {
	for ( int kind = 0; kind < 4; kind ++ ) {
		Solver solver{};
		solver.vars = 5;
		solver.initialize();
		for ( int variable = 1; variable <= solver.vars; variable ++ ) {
			solver.saved[variable] = variable % 2 == 0 ? 1 : -1;
		}
		if ( kind == 0 ) {
			// Resolve an irrelevant first assumption out of a conflict proof.
			addTestClause(solver, {2, 5});
			addTestClause(solver, {2, -5});
			addTestClause(solver, {1, 2, 3, 4}, 7);
		} else if ( kind == 1 ) {
			// A true literal terminates the prefix using its implication reason.
			addTestClause(solver, {1, 2});
			addTestClause(solver, {1, 2, 3}, 7);
		} else if ( kind == 2 ) {
			// An implied false literal can be omitted without a conflict.
			addTestClause(solver, {1, -2});
			addTestClause(solver, {1, 2, 3}, 7);
		} else {
			// Binary clauses are also eligible and may become root units.
			addTestClause(solver, {1, 3});
			addTestClause(solver, {1, -3});
			addTestClause(solver, {1, 2}, 7);
		}
		const std::vector<Clause> before = solver.clauseDB;
		assert(solver.vivifyLearnts() == 0);
		assert(solver.lcmTested == 1 && solver.lcmReduced == 1);
		if ( kind == 0 ) assert(solver.value[2] == 1);
		if ( kind == 3 ) assert(solver.value[1] == 1);
		for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
			if ( solver.clauseDB[i].learntClause ) {
				assert(solver.clauseDB[i].lbd == 7);
				assert(solver.clauseDB[i].simplified);
			}
		}
		for ( int variable = 1; variable <= solver.vars; variable ++ ) {
			assert(solver.saved[variable] == (variable % 2 == 0 ? 1 : -1));
		}
		checkRootState(solver);
		checkModels(solver, before, {});
	}
	{
		// Rank the complete list, visit its better half once, and retain LBD.
		Solver solver{};
		solver.vars = 6;
		solver.initialize();
		addTestClause(solver, {1, 2, 3}, 20);
		addTestClause(solver, {4, 5, 6}, 5);
		solver.assign(-1, 0, -1);
		const std::vector<Clause> before = solver.clauseDB;
		assert(solver.vivifyLearnts() == 0);
		assert(solver.lcmTested == 1 && solver.lcmReduced == 0);
		assert(!solver.clauseDB[0].simplified);
		assert(solver.clauseDB[0].literals.size() == 2 && solver.clauseDB[0].lbd == 20);
		assert(solver.clauseDB[1].simplified && solver.clauseDB[1].lbd == 5);
		checkModels(solver, before, {-1});
		// The newly binary first clause moves to the best half and is tested once.
		assert(solver.vivifyLearnts() == 0);
		assert(solver.lcmTested == 2);
		assert(solver.vivifyLearnts() == 0);
		assert(solver.lcmTested == 2);
		checkRootState(solver);
	}
	{
		// Automatic Chanseok selection disables the default LCM learnt path.
		Solver solver{};
		solver.vars = 3;
		solver.initialize();
		addTestClause(solver, {1, 2});
		addTestClause(solver, {1, -2});
		addTestClause(solver, {1, 3}, 2);
		solver.chanseokStrategy = true;
		assert(solver.vivifyLearnts() == 0);
		assert(solver.lcmTested == 0 && solver.value[1] == 0);
		assert(!solver.clauseDB[2].simplified);
	}
	{
		// A newly derived root unit must detect an inconsistent remainder.
		Solver solver{};
		solver.vars = 3;
		solver.initialize();
		addTestClause(solver, {1, 2});
		addTestClause(solver, {1, -2});
		addTestClause(solver, {-1, 3});
		addTestClause(solver, {-1, -3});
		addTestClause(solver, {1, 2, 3}, 3);
		assert(solver.vivifyLearnts() == 20);
		assert(solver.lcmTested == 1);
	}
	printf( "LCM_POLICY_TESTS_PASSED\n" );
	return 0;
}
