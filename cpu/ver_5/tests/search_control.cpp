#include "solver.h"
#include <cassert>
#include <cmath>

static void prepareLBDWindow( Solver &s ) {
	s.lbd_queue_size = 50;
	s.lbd_queue_pos = 7;
	s.fast_lbd_sum = 200.0;
	for ( int i = 0; i < 50; i ++ ) s.lbd_queue[i] = 4;
}

int main() {
	{
		Solver s{};
		s.initialize();
		assert(std::fabs(s.var_decay - 0.8) < 1e-12 && s.varDecayUpdates == 0);
		s.updateVSIDSDecay();
		assert(std::fabs(s.var_decay - 0.8) < 1e-12 && s.varDecayUpdates == 0);
		for ( uint64_t step = 1; step <= 20; step ++ ) {
			s.conflicts = step * 5000 - 1;
			const double previous = s.var_decay;
			s.updateVSIDSDecay();
			assert(s.var_decay == previous);
			s.conflicts ++;
			s.updateVSIDSDecay();
			const double expected = step < 15 ? 0.8 + 0.01 * step : 0.95;
			assert(std::fabs(s.var_decay - expected) < 1e-12);
			assert(s.var_decay <= 0.95);
			assert(s.varDecayUpdates == (step < 15 ? step : 15));
		}
	}
	{
		Solver s{};
		s.vars = 256;
		s.initialize();
		assert(s.trail_queue_size == 0 && s.trail_queue_sum == 0);
		s.conflicts = 9999;
		s.trail.resize(100, 1);
		prepareLBDWindow(s);
		s.slow_lbd_sum = 12345.0;
		for ( int i = 0; i < 5000; i ++ ) s.updateRestartBlocking();
		assert(s.trail_queue_size == 5000 && s.trail_queue_sum == 500000);
		assert(s.trail_queue_pos == 0 && s.blockedRestarts == 0);
		// Activation starts with the upcoming conflict numbered 10001.
		s.trail.resize(200, 1);
		s.updateRestartBlocking();
		assert(s.blockedRestarts == 0 && s.lbd_queue_size == 50);
		s.conflicts = 10000;
		const std::vector<int> trailBefore = s.trail;
		s.updateRestartBlocking();
		assert(s.blockedRestarts == 1);
		assert(s.fast_lbd_sum == 0 && s.lbd_queue_size == 0 && s.lbd_queue_pos == 0);
		assert(s.slow_lbd_sum == 12345.0 && s.trail == trailBefore);
		assert(s.restarts == 0 && s.trail_queue_sum == 500200);
		// An incomplete LBD window cannot trigger another block.
		s.updateRestartBlocking();
		assert(s.blockedRestarts == 1);
	}
	{
		Solver s{};
		s.vars = 256;
		s.initialize();
		s.conflicts = 10000;
		prepareLBDWindow(s);
		s.trail.resize(100, 1);
		for ( int i = 0; i < 4998; i ++ ) s.updateRestartBlocking();
		s.trail.resize(200, 1);
		s.updateRestartBlocking();
		assert(s.trail_queue_size == 4999 && s.blockedRestarts == 0);
		s.trail.resize(140, 1);
		s.updateRestartBlocking();
		assert(s.trail_queue_size == 5000 && s.blockedRestarts == 0);
		s.trail.resize(141, 1);
		s.updateRestartBlocking();
		assert(s.blockedRestarts == 1);
	}
	{
		// Keep long-run trail sums in 64 bits and retain them across a restart.
		Solver s{};
		s.vars = 1;
		s.initialize();
		s.trail_queue_size = 5000;
		s.trail_queue_sum = uint64_t(500000) * 5000;
		for ( int i = 0; i < 5000; i ++ ) s.trail_queue[i] = 500000;
		s.assign(1, 1, -1);
		s.decVarInTrail.push_back(0);
		s.updateRestartBlocking();
		assert(s.trail_queue_sum == uint64_t(500000) * 4999 + 1);
		const uint64_t sumBefore = s.trail_queue_sum;
		s.slow_lbd_sum = 777.0;
		prepareLBDWindow(s);
		s.restart();
		assert(s.trail.empty() && s.decVarInTrail.empty() && s.restarts == 1);
		assert(s.trail_queue_sum == sumBefore && s.trail_queue_size == 5000);
		assert(s.slow_lbd_sum == 777.0 && s.lbd_queue_size == 0 && s.fast_lbd_sum == 0);
	}
	{
		// An LBD above 50 must contribute its full value to both averages.
		Solver s{};
		s.vars = 60;
		s.initialize();
		std::vector<int> conflict;
		for ( int variable = 1; variable <= 60; variable ++ ) {
			conflict.push_back(-variable);
			s.decVarInTrail.push_back(static_cast<int>(s.trail.size()));
			s.assign(variable, variable, -1);
		}
		const int cref = s.add_clause(conflict);
		s.origin_clauses = 1;
		int backtrackLevel = 0;
		int lbd = 0;
		assert(s.analyze(cref, backtrackLevel, lbd) == 0);
		assert(lbd == 60 && backtrackLevel == 59);
		assert(s.lbd_queue_size == 1 && s.fast_lbd_sum == 60.0 && s.slow_lbd_sum == 60.0);
	}
	for ( int blocking = 0; blocking <= 1; blocking ++ ) {
		// Count an actual conflict at each policy boundary before preprocessing.
		Solver s{};
		s.vars = 2;
		s.initialize();
		for ( int a = -1; a <= 1; a += 2 ) {
			for ( int b = -1; b <= 1; b += 2 ) {
				std::vector<int> clause{a, 2 * b};
				s.add_clause(clause);
			}
		}
		s.origin_clauses = 4;
		s.conflicts = blocking ? 10000 : 4999;
		if ( blocking ) {
			prepareLBDWindow(s);
			s.slow_lbd_sum = 40000.0;
			s.trail_queue_size = 5000;
			s.trail_queue_sum = 5000;
			for ( int i = 0; i < 5000; i ++ ) s.trail_queue[i] = 1;
		}
		assert(s.decide() == 0);
		const int conflict = s.propagate();
		assert(conflict >= 0);
		s.updateRestartBlocking();
		int backtrackLevel = 0;
		int lbd = 0;
		assert(s.analyze(conflict, backtrackLevel, lbd) == 0);
		s.conflicts ++;
		s.updateVSIDSDecay();
		if ( blocking ) {
			assert(s.blockedRestarts == 1 && s.restarts == 0);
		} else {
			assert(s.conflicts == 5000 && s.varDecayUpdates == 1);
			assert(std::fabs(s.var_decay - 0.81) < 1e-12);
		}
	}
	printf( "SEARCH_CONTROL_REGRESSIONS_PASSED\n" );
}
