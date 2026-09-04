#include "solver.h"

#include <algorithm>
#include <cmath>
#include <climits>
#include <cstdlib>


#define LRB_INITIAL_STEP_SIZE 0.40
#define LRB_STEP_SIZE_DECREASE 0.000001
#define LRB_MINIMUM_STEP_SIZE 0.06
#define LRB_LOCALITY_DECAY 0.95
#define BRANCHING_INITIAL_PHASE_PROPAGATIONS 30000000ULL
#define BRANCHING_PHASE_GROWTH 1.10


// Read a positive propagation-budget option
static unsigned long long readPropagationBudget( const char *name,
						 unsigned long long defaultValue ) {
	const char *environment = getenv(name);
	if ( environment == NULL ) return defaultValue;

	char *end = NULL;
	const unsigned long long parsed = strtoull(environment, &end, 10);
	if ( end == environment || *end != '\0' || parsed == 0 ) return defaultValue;
	return parsed;
}

// Initialize LRB state and start the first LRB phase
void Solver::initializeBranching() {
	lrbActivity = new double[vars + 1];
	lrbTimestamp = new uint32_t[vars + 1];
	lrbParticipated = new uint32_t[vars + 1];
	lrbReasoned = new uint32_t[vars + 1];

	lrbStepSize = LRB_INITIAL_STEP_SIZE;
	lrbStepSizeDecrease = LRB_STEP_SIZE_DECREASE;
	lrbMinimumStepSize = LRB_MINIMUM_STEP_SIZE;
	lrbConflictClock = 0;
	branchingPropagations = 0;
	branchingPhaseBudget = readPropagationBudget(
		"UATU_BRANCH_PHASE_PROPAGATIONS",
		BRANCHING_INITIAL_PHASE_PROPAGATIONS
	);
	branchingNextSwitch = branchingPhaseBudget;
	lrbDecisions = 0;
	evsidsDecisions = 0;
	lrbUpdates = 0;
	branchingSwitches = 0;
	useLRBBranching = true;

	lrbActivity[0] = 0.0;
	lrbTimestamp[0] = 0;
	lrbParticipated[0] = 0;
	lrbReasoned[0] = 0;
	for ( int variable = 1; variable <= vars; variable ++ ) {
		lrbActivity[variable] = 0.0;
		lrbTimestamp[variable] = 0;
		lrbParticipated[variable] = 0;
		lrbReasoned[variable] = 0;
	}

	vsids.rebuild(lrbActivity, vars);
}

// Penalize a variable that has remained unassigned for several conflicts
void Solver::applyLRBLocalityDecay( int variable ) {
	const unsigned long long age = lrbConflictClock - lrbTimestamp[variable];
	if ( age == 0 ) return;

	lrbActivity[variable] *= pow(LRB_LOCALITY_DECAY, static_cast<double>(age));
	lrbTimestamp[variable] = static_cast<uint32_t>(lrbConflictClock);
	if ( useLRBBranching && vsids.inHeap(variable) ) vsids.update(variable);
}

// Start a new LRB learning interval when a variable is assigned
void Solver::recordLRBAssignment( int variable ) {
	applyLRBLocalityDecay(variable);
	lrbTimestamp[variable] = static_cast<uint32_t>(lrbConflictClock);
	lrbParticipated[variable] = 0;
	lrbReasoned[variable] = 0;
}

// Record direct and reason-side conflict participation for LRB
void Solver::recordLRBConflict( const std::vector<int> &variables ) {
	lrbConflictClock ++;
	for ( int variable : variables ) {
		if ( lrbParticipated[variable] != UINT32_MAX ) lrbParticipated[variable] ++;
	}

	++time_stamp;
	const int learntStamp = time_stamp;
	for ( int literal : learnt ) mark[abs(literal)] = learntStamp;

	for ( int literal : learnt ) {
		const int variable = abs(literal);
		const int reasonClause = reason[variable];
		if ( reasonClause < 0 ||
		     reasonClause >= static_cast<int>(clauseDB.size()) ) continue;

		const Clause &reasonData = clauseDB[reasonClause];
		for ( int reasonLiteral : reasonData.literals ) {
			const int reasonVariable = abs(reasonLiteral);
			if ( level[reasonVariable] == 0 ||
			     mark[reasonVariable] == learntStamp ) continue;

			mark[reasonVariable] = learntStamp;
			if ( lrbReasoned[reasonVariable] != UINT32_MAX ) {
				lrbReasoned[reasonVariable] ++;
			}
		}
	}

	if ( lrbStepSize > lrbMinimumStepSize ) {
		lrbStepSize = std::max(
			lrbMinimumStepSize,
			lrbStepSize - lrbStepSizeDecrease
		);
	}
}

// Finish one LRB interval when a search assignment is removed
void Solver::updateLRBOnUnassign( int variable ) {
	const unsigned long long age = lrbConflictClock - lrbTimestamp[variable];
	if ( age > 0 ) {
		const double reward =
			(static_cast<double>(lrbParticipated[variable]) +
			 static_cast<double>(lrbReasoned[variable])) /
			static_cast<double>(age);
		lrbActivity[variable] =
			lrbStepSize * reward +
			(1.0 - lrbStepSize) * lrbActivity[variable];
		lrbUpdates ++;
		if ( useLRBBranching && vsids.inHeap(variable) ) vsids.update(variable);
	}
	lrbTimestamp[variable] = static_cast<uint32_t>(lrbConflictClock);
}

// Alternate LRB and EVSIDS without changing the current assignment trail
void Solver::updateBranchingMode() {
	while ( branchingPropagations >= branchingNextSwitch ) {
		useLRBBranching = !useLRBBranching;
		branchingSwitches ++;

		if ( branchingSwitches >= 2 ) {
			const long double grown =
				static_cast<long double>(branchingPhaseBudget) *
				BRANCHING_PHASE_GROWTH;
			branchingPhaseBudget = grown >= ULLONG_MAX
				? ULLONG_MAX : static_cast<unsigned long long>(ceil(grown));
		}

		if ( ULLONG_MAX - branchingNextSwitch < branchingPhaseBudget ) {
			branchingNextSwitch = ULLONG_MAX;
		} else {
			branchingNextSwitch += branchingPhaseBudget;
		}

		vsids.rebuild(useLRBBranching ? lrbActivity : activity, vars);
		if ( branchingNextSwitch == ULLONG_MAX ) break;
	}
}
