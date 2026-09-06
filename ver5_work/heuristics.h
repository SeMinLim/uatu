#ifndef UATU_VER5_HEURISTICS_H
#define UATU_VER5_HEURISTICS_H

#include <stdint.h>
#include <vector>

#define UATU_TRAIL_WINDOW 5000
#define UATU_DECAY_INTERVAL 5000
#define UATU_BLOCK_AFTER 10000
#define UATU_VIVIFY_CANDIDATES 32
#define UATU_VIVIFY_SCAN 4096
#define UATU_VIVIFY_MAX_SIZE 32
#define UATU_VIVIFY_MAX_LBD 8
#define UATU_VIVIFY_MAX_WORK 200000

struct HeuristicOptions {
	bool adaptiveEVSIDS = true;
	bool blockedRestart = true;
	bool lbdReduction = true;
	bool recursiveMinimization = true;
	bool vivification = true;
};

struct HeuristicState {
	int trailHistory[UATU_TRAIL_WINDOW] = {};
	int trailCount = 0;
	int trailPosition = 0;
	uint64_t trailSum = 0;
	uint64_t blockedRestarts = 0;
	uint64_t decayUpdates = 0;
	uint64_t recursiveCalls = 0;
	uint64_t recursiveRemoved = 0;
	uint64_t recursiveVisits = 0;
	uint64_t protectedClauses = 0;
	uint64_t searchWork = 0;
	uint64_t vivifyWork = 0;
	uint64_t lastVivifyWork = 0;
	uint64_t vivifyRuns = 0;
	uint64_t vivifyTried = 0;
	uint64_t vivifiedClauses = 0;
	uint64_t vivifiedLiterals = 0;
	uint64_t vivifyBudgetStops = 0;
	size_t vivifyCursor = 0;
	std::vector<int> minimizeStack;
	std::vector<int> minimizeTouched;
};

class Solver;
void configureHeuristics( Solver &solver );
void recordSearchConflict( Solver &solver );
bool minimizeLearntRecursive( Solver &solver );
int vivifyAtRoot( Solver &solver );

// One credit represents one watcher or literal inspection.
static inline bool chargePropagation( HeuristicState &state, uint64_t *budget ) {
	if ( budget != nullptr ) {
		if ( *budget == 0 ) return false;
		--*budget;
		if ( state.vivifyWork != UINT64_MAX ) state.vivifyWork ++;
	} else if ( state.searchWork != UINT64_MAX ) {
		state.searchWork ++;
	}
	return true;
}

#endif
