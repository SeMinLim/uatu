from pathlib import Path
import re
import subprocess

BASE = '60e2f03e533d6d1c16995f119a876bae140bbdc5'
ROOT = Path('cpu/ver_4')

def original(name):
    return subprocess.check_output(['git', 'show', BASE + ':cpu/ver_4/' + name], text=True)

def replace_once(text, before, after):
    assert text.count(before) == 1, (before, text.count(before))
    return text.replace(before, after, 1)

h = original('solver.h')
h = replace_once(h, '#include <stdint.h>', '#include <stdint.h>\n#include <limits.h>')
h, count = re.subn(r'void initialize\(\s*const double \*s\s*\)\s*\{\s*activity = s;\s*\}', '''void initialize( const double *s, int variables ) {
		activity = s;
		heap.clear();
		heap.reserve(static_cast<size_t>(variables));
		pos.assign(static_cast<size_t>(variables) + 1, -1);
	}''', h)
assert count == 1
h = replace_once(h, 'while ( ChildLeft(v) < (int)heap.size() )', 'while ( v < (int)heap.size() / 2 )')
h = replace_once(h, 'class Solver {\npublic:', '''class Solver {
public:
	Solver() = default;
	~Solver();
	Solver( const Solver & ) = delete;
	Solver &operator = ( const Solver & ) = delete;
''')
h = replace_once(h, 'std::vector<WL> *watched_literals;', 'std::vector<WL> *watched_literals = nullptr;')
start = h.index('\tint vars, clauses, origin_clauses, conflicts;')
end = h.index('    \tint threshold;', start)
h = h[:start] + '''	int vars = 0, clauses = 0, origin_clauses = 0;
	// Search totals must not overflow after INT_MAX events.
	uint64_t conflicts = 0, decides = 0, unitPropagations = 0;
	uint64_t bcpFunctionCalls = 0;
	uint64_t restarts = 0, rephases = 0, reduces = 0;
	uint64_t rephase_inc = 0, rephase_limit = 0, reduce_limit = 0;
	uint64_t reductionRuns = 0;
	uint64_t deletedClauses = 0, minimizedLiterals = 0;
	uint64_t clauseActivityBumps = 0, dynamicLBDUpdates = 0;
''' + h[end:]
h = replace_once(h, 'int time_stamp;', 'uint32_t time_stamp;')
start = h.index('    \tint8_t *value,')
end = h.index('\n    \tdouble *activity;', start)
h = h[:start] + '''	int8_t *value = nullptr;                         // Current assignments
	int8_t *local_best = nullptr;                    // Deepest saved trail
	int8_t *saved = nullptr;                         // Saved phases
	int *reason = nullptr;                          // Implication clause indices
	int *level = nullptr;                           // Decision levels
	uint32_t *mark = nullptr;                       // Conflict-analysis stamps
	unsigned int *lbdMark = nullptr;                // Dynamic LBD stamps
	unsigned int lbdStamp;
''' + h[end:]
h = replace_once(h, 'double *activity;', 'double *activity = nullptr;')
h = replace_once(h, '\tvoid initialize();', '\tvoid nextAnalysisStamp();\n\tvoid initialize();')
start = h.index('\n};', h.index('class Solver {'))
h = h[:start] + '\nprivate:\n\tint parseStream( FILE *file );\n' + h[start:]
start = h.index('\n\n// Etc')
h = h[:start] + '\n'
(ROOT / 'solver.h').write_text(h)

s = original('solver.cpp')
start = s.index('// Functions for reading CNF')
end = s.index('//// Solver', start)
s = s[:start] + '''// Bounded DIMACS input buffering avoids retaining the whole input in memory.
struct CNFReader {
	FILE *file;
	uint8_t data[64 * 1024];
	size_t position;
	size_t length;
	bool failed;
};

static int peekCNF( CNFReader &reader ) {
	if ( reader.position == reader.length ) {
		reader.length = fread(reader.data, 1, sizeof(reader.data), reader.file);
		reader.position = 0;
		if ( reader.length == 0 ) {
			reader.failed = ferror(reader.file) != 0;
			return EOF;
		}
	}
	return reader.data[reader.position];
}

static bool isCNFSpace( int c ) {
	return c == ' ' || (c >= 9 && c <= 13);
}

static int skipCNFSpace( CNFReader &reader ) {
	int c = peekCNF(reader);
	while ( isCNFSpace(c) ) {
		reader.position ++;
		c = peekCNF(reader);
	}
	return c;
}

static bool readCNFInt( CNFReader &reader, int &value ) {
	int c = skipCNFSpace(reader);
	const bool negative = c == '-';
	if ( negative || c == '+' ) {
		reader.position ++;
		c = peekCNF(reader);
	}
	if ( c < '0' || c > '9' ) return false;

	int magnitude = 0;
	while ( c >= '0' && c <= '9' ) {
		const int digit = c - '0';
		if ( magnitude > (INT_MAX - digit) / 10 ) return false;
		magnitude = magnitude * 10 + digit;
		reader.position ++;
		c = peekCNF(reader);
	}
	if ( c != EOF && !isCNFSpace(c) ) return false;
	value = negative ? -magnitude : magnitude;
	return !reader.failed;
}

static int invalidCNF() {
	fprintf( stderr, "PARSE ERROR: invalid or incomplete DIMACS input\\n" );
	return 30;
}

''' + s[end:]
start = s.index('// Allocate memory and initialize the values')
s = s[:start] + '''// Release partially initialized arrays as well as successfully parsed formulas.
Solver::~Solver() {
	delete[] watched_literals;
	delete[] value;
	delete[] local_best;
	delete[] saved;
	delete[] reason;
	delete[] level;
	delete[] mark;
	delete[] lbdMark;
	delete[] activity;
}

// Each call begins a new marking phase; zero is reserved for unmarked entries.
void Solver::nextAnalysisStamp() {
	time_stamp ++;
	if ( time_stamp == 0 ) {
		for ( int i = 0; i <= vars; i ++ ) mark[i] = 0;
		time_stamp = 1;
	}
}

''' + s[start:]
s = replace_once(s, 'mark = new int[vars + 1];', 'mark = new uint32_t[vars + 1];')
s = replace_once(s, 'clauseDB.reserve(static_cast<size_t>(clauses) + static_cast<size_t>(clauses / 16));', 'clauseDB.reserve(static_cast<size_t>(clauses));')
s = replace_once(s, 'vsids.initialize(activity);', 'vsids.initialize(activity, vars);')
assert s.count('++time_stamp;') == 3
s = s.replace('++time_stamp;', 'nextAnalysisStamp();')
s = replace_once(s, 'const int membershipStamp = time_stamp;', 'const uint32_t membershipStamp = time_stamp;')
s = replace_once(s, '\trephase_inc *= 2;\n\trephase_limit = conflicts + rephase_inc;', '''	if ( rephase_inc <= UINT64_MAX / 2 ) rephase_inc *= 2;
	else rephase_inc = UINT64_MAX;
	if ( conflicts <= UINT64_MAX - rephase_inc ) {
		rephase_limit = conflicts + rephase_inc;
	} else {
		rephase_limit = UINT64_MAX;
	}''')
s = replace_once(s, '        reduce_limit += 512;', '''        if ( reduce_limit <= UINT64_MAX - 512 ) reduce_limit += 512;
        else reduce_limit = UINT64_MAX;''')
s = replace_once(s, 'deletedClauses += static_cast<long long>(deleteCount);', 'deletedClauses += static_cast<uint64_t>(deleteCount);')
start = s.index('// Read CNF file')
end = s.index('// Pick decision variable', start)
s = s[:start] + '''// Read CNF file. Always close the stream, including on allocation failure.
int Solver::parse( char *filename ) {
	FILE *file = fopen(filename, "rb");
	if ( !file ) {
		fprintf( stderr, "failed to open '%s': %s\\n", filename, strerror(errno) );
		return 30;
	}

	int result = 30;
	try {
		result = parseStream(file);
	} catch ( ... ) {
		fclose(file);
		throw;
	}
	fclose(file);
	return result;
}

int Solver::parseStream( FILE *file ) {
	if ( value != nullptr ) return invalidCNF();
	CNFReader reader{};
	reader.file = file;
	std::vector<int> buffer;
	buffer.reserve(16);
	bool haveHeader = false;
	bool contradictory = false;
	int parsedClauses = 0;

	while ( true ) {
		int c = skipCNFSpace(reader);
		if ( c == EOF ) break;
		if ( c == 'c' ) {
			while ( c != EOF && c != '\\n' ) {
				reader.position ++;
				c = peekCNF(reader);
			}
			continue;
		}

		if ( c == 'p' ) {
			if ( haveHeader ) return invalidCNF();
			reader.position ++;
			if ( !isCNFSpace(peekCNF(reader)) ) return invalidCNF();
			skipCNFSpace(reader);
			const char format[] = "cnf";
			for ( int i = 0; i < 3; i ++ ) {
				if ( peekCNF(reader) != format[i] ) return invalidCNF();
				reader.position ++;
			}
			if ( !isCNFSpace(peekCNF(reader)) ||
			     !readCNFInt(reader, vars) || !readCNFInt(reader, clauses) ) {
				return invalidCNF();
			}
			// Literal indices and both watcher polarities must fit signed int.
			if ( vars < 0 || vars > (INT_MAX - 1) / 2 || clauses < 0 ) {
				return invalidCNF();
			}
			initialize();
			haveHeader = true;
			continue;
		}

		if ( !haveHeader ) return invalidCNF();
		int literal = 0;
		if ( !readCNFInt(reader, literal) ) return invalidCNF();
		if ( literal != 0 ) {
			if ( literal > vars || literal < -vars ) return invalidCNF();
			buffer.push_back(literal);
		} else {
			if ( parsedClauses >= clauses ) return invalidCNF();
			parsedClauses ++;
			if ( buffer.empty() ) {
				contradictory = true;
			} else if ( buffer.size() == 1 ) {
				if ( Value(buffer[0]) == -1 ) contradictory = true;
				else if ( Value(buffer[0]) == 0 ) assign(buffer[0], 0, -1);
			} else {
				add_clause(buffer);
			}
			buffer.clear();
		}
	}

	if ( reader.failed ) {
		fprintf( stderr, "failed to read DIMACS input\\n" );
		return 30;
	}
	if ( !haveHeader || !buffer.empty() || parsedClauses != clauses ) return invalidCNF();
	origin_clauses = static_cast<int>(clauseDB.size());
	if ( contradictory ) return 20;
	return propagate() == -1 ? 0 : 20;
}

''' + s[end:]
(ROOT / 'solver.cpp').write_text(s)

(ROOT / 'main.cpp').write_text('''#include "solver.h"
#include <cstdlib>
#include <inttypes.h>
#include <new>
#include <stdexcept>


int main( int argc, char **argv ) {
	if ( argc < 2 ) {
		fprintf( stderr, "usage: %s input.cnf\\n", argv[0] );
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
		fprintf( stderr, "c OUT OF MEMORY during %s\\n", stage );
		result = 30;
	} catch ( const std::length_error & ) {
		fprintf( stderr, "c RESOURCE LIMIT: container size exceeded during %s\\n", stage );
		result = 30;
	}

	printf( "----------------------------------------------------\\n" );
	if ( result == 10 ) {
		printf( "SATISFIABLE\\n" );
		const char *print = getenv("UATU_PRINT_MODEL");
		if ( print && atoi(print) != 0 ) solver.printModel();
	} else if ( result == 20 ) {
		printf( "UNSATISFIABLE\\n" );
	} else {
		printf( "UNSOLVED\\n" );
	}

	printf( "----------------------------------------------------\\n" );
	printf( "Conflicts            : %" PRIu64 "\\n", solver.conflicts );
	printf( "Decisions            : %" PRIu64 "\\n", solver.decides );
	printf( "Unit Propagations    : %" PRIu64 "\\n", solver.unitPropagations );
	printf( "BCP Calls            : %" PRIu64 "\\n", solver.bcpFunctionCalls );
	printf( "Restarts             : %" PRIu64 "\\n", solver.restarts );
	printf( "Rephases             : %" PRIu64 "\\n", solver.rephases );
	printf( "Clause Reductions    : %" PRIu64 "\\n", solver.reductionRuns );
	printf( "Deleted Clauses      : %" PRIu64 "\\n", solver.deletedClauses );
	printf( "Minimized Literals   : %" PRIu64 "\\n", solver.minimizedLiterals );
	printf( "Clause Activity Bumps: %" PRIu64 "\\n", solver.clauseActivityBumps );
	printf( "Dynamic LBD Updates  : %" PRIu64 "\\n", solver.dynamicLBDUpdates );
	printf( "Active Clauses       : %zu\\n", solver.clauseDB.size() );
	printf( "----------------------------------------------------\\n" );
	fflush( stdout );

	return result == 10 ? 10 : (result == 20 ? 20 : 0);
}
''')
subprocess.run(['git', 'diff', '--check'], check=True)
print('PATCH_APPLIED')
