#include "solver.h"
#include <cstdlib>


int main( int argc, char **argv ) {
	if ( argc < 2 ) {
		fprintf( stderr, "usage: %s input.cnf\n", argv[0] );
		return 1;
	}

	Solver solver;
	int result = solver.parse(argv[1]);

	printf( "----------------------------------------------------\n" );
	if ( result == 20 ) {
		printf( "UNSATISFIABLE\n" );
	} else if ( result == 30 ) {
		printf( "UNSOLVED\n" );
	} else {
		result = solver.solve();
		if ( result == 10 ) {
			printf( "SATISFIABLE\n" );
			const char *print = getenv("UATU_PRINT_MODEL");
			if ( print && atoi(print) != 0 ) solver.printModel();
		} else if ( result == 20 ) {
			printf( "UNSATISFIABLE\n" );
		} else {
			printf( "UNSOLVED\n" );
		}
	}

	size_t coreClauses = 0;
	size_t tier2Clauses = 0;
	size_t localClauses = 0;
	for ( int i = solver.origin_clauses;
	      i < static_cast<int>(solver.clauseDB.size()); i ++ ) {
		if ( solver.clauseDB[i].tier == CLAUSE_CORE ) coreClauses ++;
		else if ( solver.clauseDB[i].tier == CLAUSE_TIER2 ) tier2Clauses ++;
		else if ( solver.clauseDB[i].tier == CLAUSE_LOCAL ) localClauses ++;
	}

	printf( "----------------------------------------------------\n" );
	printf( "Conflicts            : %d\n", solver.conflicts );
	printf( "Decisions            : %d\n", solver.decides );
	printf( "Unit Propagations    : %d\n", solver.unitPropagations );
	printf( "BCP Calls            : %d\n", solver.bcpFunctionCalls );
	printf( "LBD Window Resets    : %d\n", solver.lbdResets );
	printf( "Soft Rephases        : %d\n", solver.rephases );
	printf( "Clause Reductions    : %d\n", solver.reductionRuns );
	printf( "Deleted Clauses      : %lld\n", solver.deletedClauses );
	printf( "Minimized Literals   : %lld\n", solver.minimizedLiterals );
	printf( "Clause Activity Bumps: %lld\n", solver.clauseActivityBumps );
	printf( "Dynamic LBD Updates  : %lld\n", solver.dynamicLBDUpdates );
	printf( "Core Promotions      : %lld\n", solver.corePromotions );
	printf( "Tier2 Promotions     : %lld\n", solver.tier2Promotions );
	printf( "Tier2 Demotions      : %lld\n", solver.tier2Demotions );
	printf( "Core Clauses         : %zu\n", coreClauses );
	printf( "Tier2 Clauses        : %zu\n", tier2Clauses );
	printf( "Local Clauses        : %zu\n", localClauses );
	printf( "Active Clauses       : %zu\n", solver.clauseDB.size() );
	printf( "----------------------------------------------------\n" );

	return result == 10 ? 10 : (result == 20 ? 20 : 0);
}
