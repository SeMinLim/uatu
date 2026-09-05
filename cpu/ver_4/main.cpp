#include "solver.h"
#include <cstdlib>
#include <inttypes.h>
#include <new>
#include <stdexcept>


int main( int argc, char **argv ) {
	if ( argc < 2 ) {
		fprintf( stderr, "usage: %s input.cnf\n", argv[0] );
		return 1;
	}

	Solver solver{};
	int result = 30;
	const char *stage = "parsing";
	try {
		result = solver.parse(argv[1]);
		if ( result == 0 ) {
			stage = "solving";
			result = solver.solve();
		}
	} catch ( const std::bad_alloc & ) {
		fprintf( stderr, "c OUT OF MEMORY during %s\n", stage );
		result = 30;
	} catch ( const std::length_error & ) {
		fprintf( stderr, "c RESOURCE LIMIT: container size exceeded during %s\n", stage );
		result = 30;
	}

	printf( "----------------------------------------------------\n" );
	if ( result == 10 ) {
		printf( "SATISFIABLE\n" );
		const char *print = getenv("UATU_PRINT_MODEL");
		if ( print && atoi(print) != 0 ) solver.printModel();
	} else if ( result == 20 ) {
		printf( "UNSATISFIABLE\n" );
	} else {
		printf( "UNSOLVED\n" );
	}

	printf( "----------------------------------------------------\n" );
	printf( "Conflicts            : %" PRIu64 "\n", solver.conflicts );
	printf( "Decisions            : %" PRIu64 "\n", solver.decides );
	printf( "Unit Propagations    : %" PRIu64 "\n", solver.unitPropagations );
	printf( "BCP Calls            : %" PRIu64 "\n", solver.bcpFunctionCalls );
	printf( "Restarts             : %" PRIu64 "\n", solver.restarts );
	printf( "Rephases             : %" PRIu64 "\n", solver.rephases );
	printf( "Clause Reductions    : %" PRIu64 "\n", solver.reductionRuns );
	printf( "Deleted Clauses      : %" PRIu64 "\n", solver.deletedClauses );
	printf( "Minimized Literals   : %" PRIu64 "\n", solver.minimizedLiterals );
	printf( "Clause Activity Bumps: %" PRIu64 "\n", solver.clauseActivityBumps );
	printf( "Dynamic LBD Updates  : %" PRIu64 "\n", solver.dynamicLBDUpdates );
	printf( "Active Clauses       : %zu\n", solver.clauseDB.size() );
	printf( "----------------------------------------------------\n" );
	fflush( stdout );

	return result == 10 ? 10 : (result == 20 ? 20 : 0);
}
