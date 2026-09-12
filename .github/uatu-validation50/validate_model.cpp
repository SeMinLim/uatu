#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <limits.h>


// Fail without assigning a validity result to malformed input.
void fail(const char *message, const char *path) {
	printf( "INVALID: %s: %s\n", path, message );
	fflush( stdout );
	exit( 2 );
}

char *skipSpace(char *cursor) {
	while ( *cursor != '\0' && isspace( (unsigned char)*cursor ) ) cursor ++;
	return cursor;
}

char *trimLine(char *line) {
	char *begin = skipSpace(line);
	char *end = begin + strlen(begin);
	while ( end > begin && isspace( (unsigned char)end[-1] ) ) end --;
	*end = '\0';
	return begin;
}

long long readInteger(char **cursor, const char *path) {
	char *begin = skipSpace(*cursor);
	char *end = NULL;
	errno = 0;
	long long value = strtoll(begin, &end, 10);
	if ( begin == end || errno == ERANGE ||
	     (*end != '\0' && !isspace( (unsigned char)*end )) ) {
		fail("invalid integer token", path);
	}
	*cursor = end;
	return value;
}

// Keep the CNF stream positioned immediately after its header.
void readHeader(FILE *input, const char *path, int *varsNum, uint64_t *clausesNum) {
	char *line = NULL;
	size_t capacity = 0;
	while ( getline(&line, &capacity, input) >= 0 ) {
		char *cursor = skipSpace(line);
		if ( *cursor == '\0' || *cursor == 'c' ) continue;
		if ( *cursor != 'p' || !isspace( (unsigned char)cursor[1] ) ) {
			fail("missing DIMACS header before clauses", path);
		}
		cursor = skipSpace(cursor + 1);
		if ( strncmp(cursor, "cnf", 3) != 0 ||
		     !isspace( (unsigned char)cursor[3] ) ) {
			fail("expected p cnf header", path);
		}
		cursor += 3;
		long long vars = readInteger(&cursor, path);
		long long clauses = readInteger(&cursor, path);
		if ( vars < 0 || vars > INT_MAX || clauses < 0 ||
		     *skipSpace(cursor) != '\0' ) {
			fail("invalid DIMACS header counts", path);
		}
		*varsNum = (int)vars;
		*clausesNum = (uint64_t)clauses;
		free(line);
		return;
	}
	free(line);
	fail(ferror(input) ? "failed reading DIMACS header" : "missing DIMACS header", path);
}

void assignLiteral(long long literal, int varsNum, int8_t *assignment, const char *path) {
	if ( literal < -(long long)varsNum || literal > (long long)varsNum ) {
		fail("model variable is outside DIMACS header range", path);
	}
	if ( literal == 0 ) return;
	int variable = (int)(literal < 0 ? -literal : literal);
	int8_t value = literal > 0 ? 1 : -1;
	if ( assignment[variable] != 0 && assignment[variable] != value ) {
		fail("contradictory model assignments", path);
	}
	assignment[variable] = value;
}

// Uatu emits one slot per variable, including unset zeros, and one final zero.
void readUatuModel(FILE *input, const char *path, int varsNum, int8_t *assignment) {
	char *line = NULL;
	size_t capacity = 0;
	bool foundStatus = false;
	while ( getline(&line, &capacity, input) >= 0 ) {
		char *cursor = trimLine(line);
		if ( !foundStatus ) {
			if ( strcmp(cursor, "SATISFIABLE") == 0 ) foundStatus = true;
			continue;
		}
		if ( *cursor == '\0' ) continue;
		for ( long long slot = 1; slot <= (long long)varsNum; slot ++ ) {
			long long literal = readInteger(&cursor, path);
			assignLiteral(literal, varsNum, assignment, path);
			if ( literal != 0 && literal != slot && literal != -slot ) {
				fail("Uatu model slot does not match its variable", path);
			}
		}
		if ( readInteger(&cursor, path) != 0 || *skipSpace(cursor) != '\0' ) {
			fail("invalid Uatu model terminator or token count", path);
		}
		free(line);
		return;
	}
	free(line);
	fail(ferror(input) ? "failed reading model" : "missing SATISFIABLE status or model", path);
}

// MiniSAT's result file may omit unassigned variables.
void readMinisatModel(FILE *input, const char *path, int varsNum, int8_t *assignment) {
	char *line = NULL;
	size_t capacity = 0;
	bool foundStatus = false;
	bool foundTerminator = false;
	while ( getline(&line, &capacity, input) >= 0 ) {
		char *cursor = trimLine(line);
		if ( *cursor == '\0' ) continue;
		if ( !foundStatus ) {
			if ( strcmp(cursor, "SAT") != 0 ) fail("missing SAT status", path);
			foundStatus = true;
			continue;
		}
		while ( *skipSpace(cursor) != '\0' ) {
			if ( foundTerminator ) fail("tokens after model terminator", path);
			long long literal = readInteger(&cursor, path);
			if ( literal == 0 ) foundTerminator = true;
			else assignLiteral(literal, varsNum, assignment, path);
		}
	}
	free(line);
	if ( ferror(input) ) fail("failed reading model", path);
	if ( !foundStatus || !foundTerminator ) fail("missing SAT status or model terminator", path);
}

// Stream clauses, keeping satisfaction state across line boundaries.
void validateClauses(FILE *input, const char *path, int varsNum,
	uint64_t expectedClauses, const int8_t *assignment) {
	char *line = NULL;
	size_t capacity = 0;
	uint64_t clausesNum = 0;
	bool clauseSatisfied = false;
	bool pendingLiteral = false;
	while ( getline(&line, &capacity, input) >= 0 ) {
		char *cursor = skipSpace(line);
		if ( *cursor == '\0' || *cursor == 'c' ) continue;
		while ( *skipSpace(cursor) != '\0' ) {
			long long literal = readInteger(&cursor, path);
			if ( literal < -(long long)varsNum || literal > (long long)varsNum ) {
				fail("CNF literal is outside header range", path);
			}
			if ( literal == 0 ) {
				clausesNum ++;
				if ( clausesNum > expectedClauses ) fail("too many CNF clauses", path);
				if ( !clauseSatisfied ) {
					printf( "INVALID: clause=%llu vars=%d clauses=%llu has no true model literal\n",
						(unsigned long long)clausesNum, varsNum,
						(unsigned long long)expectedClauses );
					free(line);
					exit( 2 );
				}
				clauseSatisfied = false;
				pendingLiteral = false;
			} else {
				int variable = (int)(literal < 0 ? -literal : literal);
				int8_t value = literal > 0 ? 1 : -1;
				if ( assignment[variable] == value ) clauseSatisfied = true;
				pendingLiteral = true;
			}
		}
	}
	free(line);
	if ( ferror(input) ) fail("failed reading CNF clauses", path);
	if ( pendingLiteral ) fail("unterminated CNF clause", path);
	if ( clausesNum != expectedClauses ) fail("CNF clause count differs from header", path);
}

int main(int argc, char **argv) {
	if ( argc != 4 ) {
		printf( "Usage: %s input.cnf model_file uatu|minisat\n", argv[0] );
		return 2;
	}
	bool isUatu = strcmp(argv[3], "uatu") == 0;
	if ( !isUatu && strcmp(argv[3], "minisat") != 0 ) fail("unknown model format", argv[3]);
	FILE *input = fopen(argv[1], "rb");
	if ( input == NULL ) fail("cannot open CNF", argv[1]);
	FILE *model = fopen(argv[2], "rb");
	if ( model == NULL ) fail("cannot open model", argv[2]);

	// Phase 1: Read the header and emitted assignments.
	int varsNum = 0;
	uint64_t clausesNum = 0;
	readHeader(input, argv[1], &varsNum, &clausesNum);
	int8_t *assignment = (int8_t *)calloc((size_t)varsNum + 1, sizeof(int8_t));
	if ( assignment == NULL ) fail("cannot allocate model assignments", argv[1]);
	if ( isUatu ) readUatuModel(model, argv[2], varsNum, assignment);
	else readMinisatModel(model, argv[2], varsNum, assignment);
	if ( fclose(model) != 0 ) fail("cannot close model", argv[2]);

	// Phase 2: Check every original clause.
	validateClauses(input, argv[1], varsNum, clausesNum, assignment);
	if ( fclose(input) != 0 ) fail("cannot close CNF", argv[1]);
	free(assignment);
	printf( "VALID: vars=%d clauses=%llu\n", varsNum, (unsigned long long)clausesNum );
	return 0;
}
