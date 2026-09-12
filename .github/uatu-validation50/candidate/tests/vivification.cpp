#include "solver.h"
#include <cassert>
#include <algorithm>


static void addFormula( Solver &s, const std::vector<std::vector<int>> &formula ) {
	for ( std::vector<int> clause : formula ) s.add_clause(clause);
}


static bool satisfiesClause( const std::vector<int> &clause, unsigned mask ) {
	for ( int literal : clause ) {
		const bool positive = (mask & (1U << (abs(literal) - 1))) != 0;
		if ( positive == (literal > 0) ) return true;
	}
	return false;
}


static void checkReferences( const Solver &s ) {
	std::vector<int> count(s.clauseDB.size(), 0);
	for ( int literal = -s.vars; literal <= s.vars; literal ++ ) {
		if ( literal == 0 ) continue;
		for ( const WL &watch : s.watched_literals[s.vars + literal] ) {
			assert(watch.clauseIdx >= 0 && watch.clauseIdx < static_cast<int>(s.clauseDB.size()));
			const Clause &clause = s.clauseDB[watch.clauseIdx];
			assert(clause.literals.size() >= 2);
			assert(clause.literals[0] == -literal || clause.literals[1] == -literal);
			assert(std::find(clause.literals.begin(), clause.literals.end(), watch.blocker) != clause.literals.end());
			count[watch.clauseIdx] ++;
		}
	}
	for ( int watches : count ) assert(watches == 2);
	for ( int literal : s.trail ) {
		const int reason = s.reason[abs(literal)];
		if ( reason == -1 ) continue;
		assert(reason >= 0 && reason < static_cast<int>(s.clauseDB.size()));
		const std::vector<int> &clause = s.clauseDB[reason].literals;
		assert(std::find(clause.begin(), clause.end(), literal) != clause.end());
	}
}


static void checkEquivalence( const Solver &s, const std::vector<std::vector<int>> &before,
                              const std::vector<int> &roots, int result ) {
	assert(s.vars <= 10);
	for ( unsigned mask = 0; mask < (1U << s.vars); mask ++ ) {
		bool expected = true;
		for ( const std::vector<int> &clause : before ) {
			if ( !satisfiesClause(clause, mask) ) expected = false;
		}
		for ( int literal : roots ) {
			if ( !satisfiesClause({literal}, mask) ) expected = false;
		}
		bool actual = result != 20;
		for ( const Clause &clause : s.clauseDB ) {
			if ( !satisfiesClause(clause.literals, mask) ) actual = false;
		}
		for ( int literal : s.trail ) {
			assert(s.level[abs(literal)] == 0);
			if ( !satisfiesClause({literal}, mask) ) actual = false;
		}
		assert(actual == expected);
	}
}


static void runSmallProbe( const std::vector<std::vector<int>> &original,
                          const std::vector<int> &target, const std::vector<int> &roots,
                          int expectedResult, int expectedSize, int expectedUnit ) {
	Solver s{};
	s.vars = 6;
	s.initialize();
	addFormula(s, original);
	s.origin_clauses = static_cast<int>(s.clauseDB.size());
	std::vector<int> learnt = target;
	const int cref = s.add_clause(learnt);
	s.clauseDB[cref].lbd = 3;
	for ( int literal : roots ) s.assign(literal, 0, -1);
	assert(s.propagate() == -1);
	std::vector<std::vector<int>> before = original;
	before.push_back(target);
	std::vector<int8_t> saved(s.saved, s.saved + s.vars + 1);
	std::vector<int8_t> best(s.local_best, s.local_best + s.vars + 1);
	const int result = s.vivifyLearnts();
	assert(result == expectedResult);
	assert(static_cast<int>(s.clauseDB[cref].literals.size()) == expectedSize);
	assert(s.decVarInTrail.empty());
	assert(std::equal(saved.begin(), saved.end(), s.saved));
	assert(std::equal(best.begin(), best.end(), s.local_best));
	if ( expectedUnit != 0 ) assert(s.value[abs(expectedUnit)] == (expectedUnit > 0 ? 1 : -1));
	checkEquivalence(s, before, roots, result);
	checkReferences(s);
	if ( expectedResult != 20 ) {
		assert(s.propagate() == -1);
		assert(s.vivifyLearnts() == 0);
		checkEquivalence(s, before, roots, 0);
		checkReferences(s);
	}
}


int main() {
	// Detaching the target prevents it from proving its own strengthening.
	runSmallProbe({}, {1, 2, 3}, {}, 0, 3, 0);
	runSmallProbe({{1, 2}}, {1, 2, 3}, {}, 0, 2, 0);
	runSmallProbe({{1, -2}}, {1, 2, 3}, {}, 0, 2, 0);
	runSmallProbe({{1, 4}, {1, -4}}, {1, 2, 3}, {}, 0, 3, 1);
	runSmallProbe({{-1, 4}, {-1, -4}}, {-1, 2, 3}, {}, 0, 3, -1);
	runSmallProbe({{1, 2}, {1, -2}, {-1, 2}, {-1, -2}}, {1, 2, 3}, {}, 20, 3, 1);
	// Root-false literals may shorten a clause; a root reason must stay attached.
	runSmallProbe({}, {1, 2, 3}, {-2}, 0, 2, 0);
	runSmallProbe({}, {1, 2, 3}, {-2, -3}, 0, 3, 1);
	{
		// A long implication chain exhausts the budget after the target is detached.
		Solver s{};
		const int chain = 200010;
		s.vars = chain + 2;
		s.initialize();
		for ( int variable = 1; variable < chain; variable ++ ) {
			std::vector<int> clause{variable, -variable - 1};
			s.add_clause(clause);
		}
		s.origin_clauses = static_cast<int>(s.clauseDB.size());
		std::vector<int> target{1, chain + 1, chain + 2};
		const int cref = s.add_clause(target);
		s.clauseDB[cref].lbd = 3;
		const std::vector<int8_t> saved(s.saved, s.saved + s.vars + 1);
		assert(s.vivifyLearnts() == 0);
		assert(s.vivificationCandidates == 1 && s.vivificationBudgetStops == 1);
		assert(s.vivifiedClauses == 0 && s.clauseDB[cref].literals == target);
		assert(s.trail.empty() && s.decVarInTrail.empty() && s.propagated == 0);
		for ( int variable = 1; variable <= s.vars; variable ++ ) {
			assert(s.value[variable] == 0 && s.reason[variable] == -1 && s.level[variable] == 0);
		}
		assert(std::equal(saved.begin(), saved.end(), s.saved));
		checkReferences(s);
		// The restored watches still propagate the complete chain and target.
		s.assign(-1, 0, -1);
		s.assign(-chain - 1, 0, -1);
		assert(s.propagate() == -1 && s.value[chain] == -1 && s.value[chain + 2] == 1);
		checkReferences(s);
	}
	printf( "VIVIFICATION_REGRESSIONS_PASSED\n" );
	return 0;
}
