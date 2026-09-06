#ifndef UATU_VER5_HEURISTICS_H
#define UATU_VER5_HEURISTICS_H

#include <stdint.h>
#include <vector>

class Solver;

// CPU policies are selected independently of the propagation implementation.
struct HeuristicState {
	bool adaptiveEVSIDS = true;
	bool blockedRestart = true;
	bool lbdReduction = true;
	bool recursiveMinimization = true;
	bool vivification = true;
	bool rephase = true;

	uint64_t blockedRestarts = 0;
	uint64_t decayUpdates = 0;
	uint64_t protectedClauses = 0;
	uint64_t recursiveCalls = 0;
	uint64_t recursiveVisits = 0;
	uint64_t vivificationRuns = 0;
	uint64_t vivificationAttempts = 0;
	uint64_t vivifiedClauses = 0;
	uint64_t vivifiedLiterals = 0;
	uint64_t vivificationUnits = 0;
	uint64_t vivificationAborts = 0;
	uint64_t propagationWork = 0;
	uint64_t previousWork = 0;
	uint64_t probeEnd = 0;
	bool probing = false;

	int trailQueue[5000] = {};
	int trailQueueSize = 0;
	int trailQueuePos = 0;
	uint64_t trailSum = 0;
	int vivifyCursor = 0;
	std::vector<unsigned char> minKnown;
	std::vector<int> minTouched;
	std::vector<int> minStack;
};

void configureHeuristics( Solver &solver );
void observeConflictTrail( Solver &solver );
void updateAdaptiveDecay( Solver &solver );
void minimizeLearnedClauseRecursive( Solver &solver );
bool vivifyLearnedClauses( Solver &solver );
void printHeuristicStatistics( const Solver &solver );

#endif
