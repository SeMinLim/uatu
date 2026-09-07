#include <sys/resource.h>
#include <stdio.h>
#include <stdint.h>
#include <limits.h>
#include <stdlib.h>
#include <stdbool.h>
#include <vector>

// Inspect the minimizer without adding production test interfaces.
#define private public
#include "solver.h"
#undef private
#include <cassert>

static bool satisfiesClause( const std::vector<int> &clause, unsigned mask ) {
	for ( int literal : clause ) {
		const bool positive = (mask & (1U << (abs(literal) - 1))) != 0;
		if ( positive == (literal > 0) ) return true;
	}
	return false;
}

// Exhaustively prove that premises and the original learnt imply its reduction.
static void checkImplication( const Solver &s, const std::vector<int> &before,
		const std::vector<int> &roots = {} ) {
	assert(s.vars <= 10);
	for ( unsigned mask = 0; mask < (1U << s.vars); mask ++ ) {
		bool premise = satisfiesClause(before, mask);
		for ( int root : roots ) {
			const bool positive = (mask & (1U << (abs(root) - 1))) != 0;
			if ( positive != (root > 0) ) premise = false;
		}
		for ( const Clause &clause : s.clauseDB ) {
			if ( !satisfiesClause(clause.literals, mask) ) premise = false;
		}
		if ( premise ) assert(satisfiesClause(s.learnt, mask));
	}
}

int main() {
	{
		// A multi-edge proof reaches a retained literal and a root assignment.
		Solver s{};
		s.vars = 8;
		s.initialize();
		std::vector<int> first{2, -1};
		std::vector<int> second{3, -2};
		std::vector<int> third{4, -3, -8};
		const int a = s.add_clause(first);
		const int b = s.add_clause(second);
		const int c = s.add_clause(third);
		s.assign(8, 0, -1);
		s.assign(1, 1, -1);
		s.assign(2, 1, a);
		s.assign(3, 1, b);
		s.assign(4, 1, c);
		s.assign(5, 2, -1);
		s.learnt = {-5, -4, -1};
		const std::vector<int> before = s.learnt;
		s.minimizeLearntRecursive();
		assert((s.learnt == std::vector<int>{-5, -1}));
		assert(s.minimizedLiterals == 1);
		checkImplication(s, before, {8});
	}
	{
		// A failed proof must not leave a cached shared reason for the next literal.
		Solver s{};
		s.vars = 6;
		s.initialize();
		std::vector<int> shared{3, -2};
		std::vector<int> first{4, -3, -1};
		std::vector<int> second{5, -3};
		const int a = s.add_clause(shared);
		const int b = s.add_clause(first);
		const int c = s.add_clause(second);
		s.assign(1, 1, -1);
		s.assign(2, 2, -1);
		s.assign(3, 2, a);
		s.assign(4, 2, b);
		s.assign(5, 2, c);
		s.assign(6, 3, -1);
		s.learnt = {-6, -4, -5, -1};
		const std::vector<int> before = s.learnt;
		s.minimizeLearntRecursive();
		assert(s.learnt == before && s.minimizedLiterals == 0);
		assert(s.mark[3] != s.time_stamp);
		assert(s.minimizeStack.empty() && s.minimizeTouched.empty());
		checkImplication(s, before);
	}
	for ( int assertingSign = -1; assertingSign <= 1; assertingSign += 2 ) {
		for ( int partnerSign = -1; partnerSign <= 1; partnerSign += 2 ) {
			for ( int kind = 0; kind < 4; kind ++ ) {
				Solver s{};
				s.vars = 4;
				s.initialize();
				const int p = assertingSign;
				const int q = 2 * partnerSign;
				std::vector<int> clause{p, -q};
				if ( kind == 1 ) clause[1] = q;
				if ( kind == 2 ) clause[0] = -p;
				if ( kind == 3 ) clause.push_back(4);
				s.add_clause(clause);
				s.assign(-q, 1, -1);
				s.assign(3, 1, -1);
				s.assign(-p, 2, -1);
				s.learnt = {p, q, -3};
				const std::vector<int> before = s.learnt;
				s.minimizeLearntBinary();
				if ( kind == 0 ) {
					assert((s.learnt == std::vector<int>{p, -3}));
					assert(s.minimizedLiterals == 1);
				} else {
					assert(s.learnt == before && s.minimizedLiterals == 0);
				}
				checkImplication(s, before);
			}
		}
	}
	{
		// Unit learnt clauses retain their asserting literal in both minimizers.
		Solver s{};
		s.vars = 1;
		s.initialize();
		s.learnt = {-1};
		s.minimizeLearntRecursive();
		s.minimizeLearntBinary();
		assert((s.learnt == std::vector<int>{-1}));
		assert(s.minimizedLiterals == 0);
	}
	printf( "MINIMIZATION_REGRESSIONS_PASSED\n" );
}
