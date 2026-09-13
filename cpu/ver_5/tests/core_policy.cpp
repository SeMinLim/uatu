#include "../solver.h"
#include <cmath>

static void require( bool condition, const char *message ) {
	if ( condition ) return;
	fprintf( stderr, "core policy check failed: %s\n", message );
	exit(1);
}

static void initializeSolver( Solver &solver, int variables ) {
	solver.vars = variables;
	solver.initialize();
}

static int addLearnt( Solver &solver, const std::vector<int> &literals,
	int lbd, double activity ) {
	std::vector<int> copy = literals;
	const int id = solver.add_clause(copy);
	solver.clauseDB[id].learntClause = true;
	solver.clauseDB[id].lbd = lbd;
	solver.clauseDB[id].activity = activity;
	return id;
}

static bool hasClause( const Solver &solver, const std::vector<int> &literals ) {
	for ( const Clause &clause : solver.clauseDB ) {
		if ( !clause.removed && clause.literals == literals ) return true;
	}
	return false;
}

// A two-edge reason chain distinguishes deep minimization from a one-step check.
static void checkMinimization() {
	Solver solver;
	initializeSolver(solver, 5);
	std::vector<int> firstReason = {2, -3};
	std::vector<int> secondReason = {3, -1};
	solver.reason[2] = solver.add_clause(firstReason);
	solver.reason[3] = solver.add_clause(secondReason);
	solver.level[1] = solver.level[2] = solver.level[3] = 1;
	solver.value[1] = solver.value[2] = solver.value[3] = 1;
	solver.nextAnalysisStamp();
	solver.mark[1] = solver.time_stamp;
	solver.mark[2] = solver.time_stamp;
	require(solver.literalRedundant(-2, uint32_t(1) << 1),
		"recursive minimization follows a multi-edge reason chain");
	solver.nextAnalysisStamp();
	solver.mark[1] = solver.time_stamp;
	solver.mark[2] = solver.time_stamp;
	solver.reason[3] = -1;
	require(!solver.literalRedundant(-2, uint32_t(1) << 1),
		"a missing antecedent reason prevents unsound minimization");
	std::vector<int> binary = {-5, 2};
	solver.add_clause(binary);
	solver.learnt = {-5, -2, -3};
	solver.level[5] = 3;
	solver.level[2] = 2;
	solver.binaryMinimization();
	require(solver.learnt == std::vector<int>({-5, -3}),
		"binary resolution removes the implied learnt-clause literal");
}

// LBD improvement must count root assignments and retain its strict threshold.
static void checkDynamicLBD() {
	Solver solver;
	initializeSolver(solver, 3);
	solver.level[1] = 0;
	solver.level[2] = solver.level[3] = 1;
	const int id = addLearnt(solver, {1, 2, 3}, 3, 0.0);
	require(solver.calculateClauseLBD(solver.clauseDB[id]) == 2,
		"dynamic LBD includes decision level zero");
	solver.updateClauseQuality(id);
	require(solver.clauseDB[id].lbd == 3 && solver.clauseDB[id].removable,
		"one-level LBD improvement must not trigger an update");
	solver.clauseDB[id].lbd = 4;
	solver.updateClauseQuality(id);
	require(solver.clauseDB[id].lbd == 2 && !solver.clauseDB[id].removable,
		"improved low-LBD learnt clause receives one-round protection");
	solver.clauseDB[id].lbd = 31;
	solver.clauseDB[id].removable = true;
	solver.updateClauseQuality(id);
	require(solver.clauseDB[id].lbd == 2 && solver.clauseDB[id].removable,
		"old LBD above 30 receives no temporary protection");
	solver.clauseDB[id].lbd = 8;
	solver.chanseokStrategy = true;
	solver.coLBDBound = 3;
	solver.updateClauseQuality(id);
	require(solver.clauseDB[id].permanent,
		"Chanseok promotion retains a newly low-LBD clause permanently");
}

// Reduction must keep the live implication graph and protected clauses intact.
static void checkReduction() {
	Solver solver;
	initializeSolver(solver, 20);
	const std::vector<int> lockedClause = {3, 1, 2};
	const int locked = addLearnt(solver, lockedClause, 40, 0.0);
	for ( int i = 4; i < 13; i ++ ) {
		addLearnt(solver, {i, 19, 20}, 40 - i, i);
	}
	const std::vector<int> binaryClause = {14, 15};
	const std::vector<int> glueClause = {16, 19, 20};
	const std::vector<int> activeClause = {17, 19, 20};
	const std::vector<int> protectedClause = {18, 19, 20};
	addLearnt(solver, binaryClause, 2, 0.0);
	addLearnt(solver, glueClause, 2, 0.0);
	addLearnt(solver, activeClause, 35, 1000.0);
	const int protectedId = addLearnt(solver, protectedClause, 39, 0.0);
	solver.clauseDB[protectedId].removable = false;
	solver.decVarInTrail.push_back(0);
	solver.assign(-1, 1, -1);
	solver.assign(-2, 1, -1);
	solver.assign(3, 1, locked);
	solver.propagated = static_cast<int>(solver.trail.size());
	const std::vector<int> trailBefore = solver.trail;
	solver.reduce();
	require(solver.deletedClauses > 0, "reduction actually deletes low-quality learnts");
	require(solver.trail == trailBefore && solver.decVarInTrail.size() == 1,
		"reduction preserves the active trail and decision level");
	const int reason = solver.reason[3];
	require(reason >= 0 && reason < static_cast<int>(solver.clauseDB.size()),
		"live reason index survives compaction");
	require(solver.clauseDB[reason].literals == lockedClause,
		"live reason still names the same clause");
	require(hasClause(solver, binaryClause) && hasClause(solver, glueClause),
		"binary and glue clauses survive reduction");
	require(hasClause(solver, activeClause) && hasClause(solver, protectedClause),
		"activity and temporary protection survive reduction");
}

static void setAdaptationStatistics( Solver &solver, uint64_t decisions,
	uint64_t successiveConflicts ) {
	solver.conflicts = 100000;
	solver.decides = decisions;
	solver.noDecisionConflict = successiveConflicts;
	solver.lbd_queue_size = 50;
	solver.fast_lbd_sum = 500;
	solver.slow_lbd_sum = 1000000;
	solver.conflictsRestarts = 100000;
	solver.trail_queue_size = 5000;
	solver.trailQueueSum = 123456;
}

// These samples exercise overlapping adaptation decisions and state migration.
static void checkAdaptation() {
	{
		Solver solver;
		initializeSolver(solver, 6);
		setAdaptationStatistics(solver, 120000, 40000);
		addLearnt(solver, {1, 2, 3}, 4, 0.0);
		addLearnt(solver, {4, 5, 6}, 5, 0.0);
		solver.activity[1] = 123.0;
		solver.saved[1] = 1;
		solver.adaptSolver();
		require(solver.chanseokStrategy && solver.coLBDBound == 4,
			"low decisions/conflicts activates Chanseok bound four");
		require(solver.nbclausesbeforereduce == 2000 && solver.curRestart == 51 &&
			solver.incReduceDB == 0, "low-decision adaptation resets reduction schedule");
		require(hasClause(solver, {1, 2, 3}) && !hasClause(solver, {4, 5, 6}),
			"reinitialization keeps permanent learnts and removes remaining learnts");
		require(solver.lbd_queue_size == 0 && solver.slow_lbd_sum == 0 &&
			solver.conflictsRestarts == 0, "adaptation resets both restart-average components");
		require(solver.trailQueueSum == 123456 && solver.trail_queue_size == 5000,
			"adaptation retains the trail-length history");
		require(solver.activity[1] == 123.0 && solver.saved[1] == 1,
			"adaptation preserves branching activity and saved phases");
	}
	{
		Solver solver;
		initializeSolver(solver, 3);
		setAdaptationStatistics(solver, 130000, 29999);
		solver.adaptSolver();
		require(solver.lubyRestart && !solver.chanseokStrategy &&
			std::fabs(solver.var_decay - 0.999) < 1e-12 &&
			std::fabs(solver.max_var_decay - 0.999) < 1e-12,
			"low successive-conflict frequency enables Luby and long activity memory");
	}
	{
		Solver solver;
		initializeSolver(solver, 3);
		setAdaptationStatistics(solver, 130000, 54401);
		solver.nbclausesbeforereduce = 7300;
		solver.learntGlue = 21002;
		solver.learntBinary = 1001;
		solver.adaptSolver();
		require(solver.chanseokStrategy && solver.coLBDBound == 3 &&
			solver.randomizeOnRestarts, "high successive-conflict frequency changes retention and phase");
		require(solver.firstReduceDB == 30000 && solver.nbclausesbeforereduce == 7300,
			"high-conflict adaptation preserves the running reduction interval");
		require(std::fabs(solver.var_decay - 0.91) < 1e-12 &&
			std::fabs(solver.max_var_decay - 0.91) < 1e-12,
			"many nonbinary glue clauses override the preceding decay choice");
	}
	{
		Solver solver;
		initializeSolver(solver, 3);
		setAdaptationStatistics(solver, 130000, 30000);
		solver.learntGlue = 21000;
		solver.learntBinary = 1000;
		solver.adaptSolver();
		require(!solver.lubyRestart && !solver.chanseokStrategy &&
			solver.conflictsRestarts == 100000,
			"boundary statistics leave the default strategy and history intact");
	}
}

static void checkRestartsAndPhases() {
	Solver solver;
	initializeSolver(solver, 5);
	solver.lbd_queue_size = 50;
	solver.fast_lbd_sum = 249;
	solver.conflictsRestarts = 100;
	solver.slow_lbd_sum = 350;
	require(!solver.shouldRestart(0, 0), "LBD restarts use the integer moving average");
	solver.fast_lbd_sum = 250;
	require(solver.shouldRestart(0, 0), "LBD deterioration requests a restart");
	solver.lubyRestart = true;
	require(!solver.shouldRestart(99, 100) && solver.shouldRestart(100, 100),
		"Luby uses the per-search conflict budget");
	const uint64_t expected[] = {1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8};
	for ( size_t i = 0; i < sizeof(expected) / sizeof(expected[0]); i ++ ) {
		require(Solver::luby(i) == expected[i], "Luby sequence");
	}
	solver.forceUNSAT[1] = 1;
	solver.update_score(1, 10.0);
	require(solver.decide() == 0 && solver.trail.back() == -1,
		"initial decisions use false phase even with a recorded force phase");
	solver.restart();
	require(solver.newDescent && solver.decide() == 0 && solver.trail.back() == 1,
		"restart activates the recorded conflict phase");
	solver.backtrack(0);
	solver.newDescent = false;
	solver.forceUNSAT[1] = -1;
	require(solver.decide() == 0 && solver.trail.back() == 1,
		"outside a new descent, full phase saving determines polarity");
	solver.backtrack(0);
	solver.newDescent = true;
	solver.randomizeOnRestarts = true;
	solver.randomDescentAssignments = 1;
	solver.forceUNSAT[1] = 1;
	require(solver.decide() == 0 && solver.trail.back() == -1,
		"enabled randomized even-level phase takes priority over Force-UNSAT");
}

static void checkRestartBlocking() {
	Solver solver;
	initializeSolver(solver, 150);
	for ( int variable = 1; variable <= 141; variable ++ ) solver.assign(variable, 0, -1);
	for ( int i = 0; i < 5000; i ++ ) solver.trail_queue[i] = 100;
	solver.trail_queue_size = 5000;
	solver.trailQueueSum = 500000;
	solver.lbd_queue_size = 50;
	solver.fast_lbd_sum = 500;
	solver.slow_lbd_sum = 100000;
	solver.conflictsRestarts = 10000;
	solver.pushTrailSize();
	require(solver.lbd_queue_size == 50,
		"restart blocking stays inactive at the lower conflict bound");
	solver.conflictsRestarts = 10001;
	solver.pushTrailSize();
	require(solver.lbd_queue_size == 0 && solver.blockedRestarts == 1,
		"a sufficiently long trail blocks restarts after the lower bound");
	require(solver.slow_lbd_sum == 100000 && solver.conflictsRestarts == 10001,
		"blocking preserves the long-term LBD average");
}

int main() {
	checkMinimization();
	checkDynamicLBD();
	checkReduction();
	checkAdaptation();
	checkRestartsAndPhases();
	checkRestartBlocking();
	printf( "---------------------------------------------------------------------\n" );
	printf( "[STEP 1] Glucose core policy checks passed.\n" );
	printf( "---------------------------------------------------------------------\n" );
	fflush( stdout );
	return 0;
}
