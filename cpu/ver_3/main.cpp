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
	printf( "Active Clauses       : %zu\n", solver.clauseDB.size() );
	printf( "----------------------------------------------------\n" );

	return result == 10 ? 10 : (result == 20 ? 20 : 0);
}
