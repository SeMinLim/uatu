#include "solver.h"
#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <utility>


#ifndef UATU_PROFILE_BCP
#define UATU_PROFILE_BCP 0
#endif


// Required functions
// Elapsed time checker
static inline double timeCheckerCPU( void ) {
	struct rusage ru;
	getrusage(RUSAGE_SELF, &ru);

	return (double)ru.ru_utime.tv_sec + (double)ru.ru_utime.tv_usec / 1000000;
}

#if UATU_PROFILE_BCP
typedef std::chrono::steady_clock BcpClock;

static inline void finishBCPTiming( Solver &solver, const BcpClock::time_point &start ) {
	const double seconds = std::chrono::duration<double>(BcpClock::now() - start).count();
	solver.propagaTimeFinal += seconds;
	if ( seconds > solver.maxBCPTime ) solver.maxBCPTime = seconds;
}
#endif

// Bounded DIMACS input buffering avoids retaining the whole input in memory.
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
	fprintf( stderr, "PARSE ERROR: invalid or incomplete DIMACS input\n" );
	return 30;
}

// Solver
// Release partially initialized arrays as well as successfully parsed formulas.
Solver::~Solver() {
	delete[] watched_literals;
	delete[] value;
	delete[] forceUNSAT;
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

// Allocate memory and initialize the values
void Solver::initialize( void ) {
	value = new int8_t[vars + 1];
	forceUNSAT = new int8_t[vars + 1];
	saved = new int8_t[vars + 1];
	reason = new int[vars + 1];
	level = new int[vars + 1];
	mark = new uint32_t[vars + 1];
	lbdMark = new unsigned int[vars + 1];
	activity = new double[vars + 1];
	watched_literals = new std::vector<WL>[vars * 2 + 1];

	clauseDB.reserve(static_cast<size_t>(clauses));
	trail.reserve(vars);
	decVarInTrail.reserve(vars);
	learnt.reserve(64);

	conflicts = decides = unitPropagations = bcpFunctionCalls = 0;
	restarts = reduces = 0;
	reductionRuns = 0;
	deletedClauses = minimizedLiterals = 0;
	clauseActivityBumps = dynamicLBDUpdates = 0;
	propagated = time_stamp = 0;
	lbdStamp = 0;
	fast_lbd_sum = lbd_queue_size = lbd_queue_pos = slow_lbd_sum = 0;
	processTimeFinal = propagaTimeFinal = maxBCPTime = 0.0;

	var_inc = 1;
	var_decay = 0.8;
	clause_inc = 1.0;
	clause_decay = 0.999;
	eliminated.assign(static_cast<size_t>(vars) + 1, 0);

	vsids.initialize(activity, vars);
	value[0] = forceUNSAT[0] = saved[0] = 0;
	reason[0] = -1;
	level[0] = mark[0] = 0;
	lbdMark[0] = 0;
	activity[0] = 0.0;
	for ( int i = 1; i <= vars; i ++ ) {
		value[i] = forceUNSAT[i] = 0;
		saved[i] = -1;
		reason[i] = -1;
		level[i] = mark[i] = 0;
		lbdMark[i] = 0;
		activity[i] = 0.0;
		vsids.insert(i);
	}
}

// Assign 'true' value to a certain literal
void Solver::assign( int literal, int l, int cref ) {
	// Only make the literal 'true'
	// Assign 'true' if a selected literal has positive value
	// Assign 'false' if a selected literal has negative value
	int var = abs(literal);
	value[var] = literal > 0 ? 1 : -1;
	level[var] = l;
	reason[var] = cref;
	trail.push_back(literal);
}

// Add a clause to the database
int Solver::add_clause( std::vector<int> &c ) {
	clauseDB.push_back(Clause(c.size()));

	int id = clauseDB.size() - 1;
	for ( int i = 0; i < (int)c.size(); i ++ ) clauseDB[id][i] = c[i];

	// Two watched literals
	// We only make the literals 'true'
	// Then our only concern is the opposite ones, -c[0] and -c[1]
	// c[0] is a blocker for c[1] and vice versa
	WatchedLiterals(-c[0]).push_back(WL(id, c[1]));
	WatchedLiterals(-c[1]).push_back(WL(id, c[0]));

	return id;
}

// BCP (Boolean Constraint Propagation)
int Solver::propagate( void ) {
	bcpFunctionCalls ++;
#if UATU_PROFILE_BCP
	const BcpClock::time_point bcpStart = BcpClock::now();
#endif

	while ( propagated < static_cast<int>(trail.size()) ) {
		const int p = trail[propagated ++];
		if ( simpDBProps > INT64_MIN ) simpDBProps --;
		std::vector<WL> &ws = WatchedLiterals(p);
		const int numClauses = static_cast<int>(ws.size());
		int out = 0;

		for ( int i = 0; i < numClauses; ) {
			const int blocker = ws[i].blocker;
			if ( Value(blocker) == 1 ) {
				ws[out ++] = ws[i ++];
				continue;
			}

			const int cref = ws[i].clauseIdx;
			Clause &c = clauseDB[cref];
			const int falseLiteral = -p;
			if ( c[0] == falseLiteral ) {
				c[0] = c[1];
				c[1] = falseLiteral;
			}
			i ++;

			const int firstWatch = c[0];
			const WL watcher(cref, firstWatch);
			if ( Value(firstWatch) == 1 ) {
				ws[out ++] = watcher;
				continue;
			}

			int k = 2;
			const int size = static_cast<int>(c.literals.size());
			while ( k < size && Value(c[k]) == -1 ) k ++;

			if ( k < size ) {
				c[1] = c[k];
				c[k] = falseLiteral;
				WatchedLiterals(-c[1]).push_back(watcher);
			} else {
				ws[out ++] = watcher;
				if ( Value(firstWatch) == -1 ) {
					while ( i < numClauses ) ws[out ++] = ws[i ++];
					ws.resize(out);
#if UATU_PROFILE_BCP
					finishBCPTiming(*this, bcpStart);
#endif
					return cref;
				}

				assign(firstWatch, level[abs(p)], cref);
				unitPropagations ++;
			}
		}
		ws.resize(out);
	}

#if UATU_PROFILE_BCP
	finishBCPTiming(*this, bcpStart);
#endif
	return -1;
}

// Read CNF file. Always close the stream, including on allocation failure.
int Solver::parse( char *filename ) {
	FILE *file = fopen(filename, "rb");
	if ( !file ) {
		fprintf( stderr, "failed to open '%s': %s\n", filename, strerror(errno) );
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
			while ( c != EOF && c != '\n' ) {
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
			std::sort(buffer.begin(), buffer.end());
			buffer.erase(std::unique(buffer.begin(), buffer.end()), buffer.end());
			bool satisfied = false;
			for ( size_t i = 0; i < buffer.size(); i ++ ) {
				const int current = buffer[i];
				if ( Value(current) == 1 || (current > 0 &&
				     std::binary_search(buffer.begin(), buffer.end(), -current)) ) {
					satisfied = true;
					break;
				}
			}
			if ( !satisfied ) {
				size_t out = 0;
				for ( size_t i = 0; i < buffer.size(); i ++ ) {
					const int current = buffer[i];
					if ( Value(current) != -1 ) buffer[out ++] = current;
				}
				buffer.resize(out);
				if ( buffer.empty() ) contradictory = true;
				else if ( buffer.size() == 1 ) assign(buffer[0], 0, -1);
				else add_clause(buffer);
			}
			buffer.clear();
		}
	}

	if ( reader.failed ) {
		fprintf( stderr, "failed to read DIMACS input\n" );
		return 30;
	}
	if ( !haveHeader || !buffer.empty() || parsedClauses != clauses ) return invalidCNF();
	origin_clauses = static_cast<int>(clauseDB.size());
	if ( contradictory ) return 20;
	return propagate() == -1 ? 0 : 20;
}

// Pick decision variable based on VSIDS and the active descent phase policy.
int Solver::decide() {
	decides ++;
	int next = 0;
	while ( !vsids.empty() ) {
		const int variable = vsids.pop();
		if ( value[variable] == 0 && !eliminated[variable] ) {
			next = variable;
			break;
		}
	}
	if ( next == 0 ) return 10;

	const int decisionLevel = static_cast<int>(decVarInTrail.size());
	int phase = saved[next];
	if ( phase == 0 ) phase = -1;
	if ( randomizeOnRestarts && newDescent && decisionLevel % 2 == 0 ) {
		phase = ((randomDescentAssignments >> (decisionLevel % 32)) & 1) ? -1 : 1;
	} else if ( newDescent && forceUNSAT[next] != 0 ) {
		phase = forceUNSAT[next];
	}
	decVarInTrail.push_back(static_cast<int>(trail.size()));
	assign(next * phase, decisionLevel + 1, -1);
	return 0;
}

// Update variable activity.
void Solver::update_score( int variable, double coefficient ) {
	activity[variable] += var_inc * coefficient;
	if ( activity[variable] > 1e100 ) {
		for ( int i = 1; i <= vars; i ++ ) activity[i] *= 1e-100;
		var_inc *= 1e-100;
	}
	if ( vsids.inHeap(variable) ) vsids.update(variable);
}

// Update learnt-clause activity.
void Solver::bumpClauseActivity( int cref ) {
	if ( cref < 0 || cref >= static_cast<int>(clauseDB.size()) ) return;
	Clause &clause = clauseDB[cref];
	if ( !clause.learntClause || clause.removed ) return;
	clause.activity += clause_inc;
	if ( clause.useCount != UINT32_MAX ) clause.useCount ++;
	clauseActivityBumps ++;
	if ( clause.activity > 1e20 ) {
		for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
			Clause &other = clauseDB[i];
			if ( other.learntClause ) other.activity *= 1e-20;
		}
		clause_inc *= 1e-20;
	}
}

// Count every represented level, including level zero, as Glucose does.
int Solver::calculateClauseLBD( const Clause &clause ) {
	return calculateLBD(clause.literals);
}

int Solver::calculateLBD( const std::vector<int> &literals ) {
	lbdStamp ++;
	if ( lbdStamp == 0 ) {
		for ( int i = 0; i <= vars; i ++ ) lbdMark[i] = 0;
		lbdStamp = 1;
	}
	int currentLBD = 0;
	for ( size_t i = 0; i < literals.size(); i ++ ) {
		const int literal = literals[i];
		const int decisionLevel = level[abs(literal)];
		if ( lbdMark[decisionLevel] != lbdStamp ) {
			lbdMark[decisionLevel] = lbdStamp;
			currentLBD ++;
		}
	}
	return currentLBD;
}

void Solver::updateClauseQuality( int cref ) {
	if ( cref < 0 || cref >= static_cast<int>(clauseDB.size()) ) return;
	Clause &clause = clauseDB[cref];
	if ( !clause.learntClause || clause.removed ) return;
	bumpClauseActivity(cref);
	if ( clause.lbd <= 2 ) return;
	const int currentLBD = calculateClauseLBD(clause);
	if ( currentLBD + 1 >= clause.lbd ) return;
	if ( clause.lbd <= 30 ) clause.removable = false;
	if ( chanseokStrategy && currentLBD <= coLBDBound ) {
		if ( !clause.permanent && ordinaryLearntCount > 0 ) ordinaryLearntCount --;
		clause.learntClause = false;
		clause.permanent = true;
	} else {
		clause.lbd = currentLBD;
	}
	dynamicLBDUpdates ++;
}

// Follow the complete implication graph; roll back only this attempt on failure.
bool Solver::literalRedundant( int literal, uint32_t abstractLevels ) {
	analyzeStack.clear();
	analyzeStack.push_back(literal);
	const size_t previousSize = analyzeToClear.size();
	while ( !analyzeStack.empty() ) {
		const int variable = abs(analyzeStack.back());
		analyzeStack.pop_back();
		const int cref = reason[variable];
		if ( cref < 0 || cref >= static_cast<int>(clauseDB.size()) ) return false;
		for ( size_t i = 0; i < clauseDB[cref].literals.size(); i ++ ) {
			const int other = clauseDB[cref].literals[i];
			const int otherVariable = abs(other);
			if ( otherVariable == variable || level[otherVariable] == 0 ||
			     mark[otherVariable] == time_stamp ) continue;
			if ( reason[otherVariable] >= 0 &&
			     (abstractLevels & (UINT32_C(1) << (level[otherVariable] & 31))) != 0 ) {
				mark[otherVariable] = time_stamp;
				analyzeStack.push_back(other);
				analyzeToClear.push_back(otherVariable);
			} else {
				for ( size_t i = previousSize; i < analyzeToClear.size(); i ++ ) {
					mark[analyzeToClear[i]] = 0;
				}
				analyzeToClear.resize(previousSize);
				return false;
			}
		}
	}
	return true;
}

// Resolve small learnt clauses with binaries containing the asserting literal.
void Solver::binaryMinimization() {
	if ( learnt.size() < 2 || learnt.size() > 30 ) return;
	if ( calculateLBD(learnt) > 6 ) return;
	nextAnalysisStamp();
	for ( size_t i = 1; i < learnt.size(); i ++ ) mark[abs(learnt[i])] = time_stamp;
	const std::vector<WL> &watchers = WatchedLiterals(-learnt[0]);
	for ( size_t i = 0; i < watchers.size(); i ++ ) {
		const WL &watcher = watchers[i];
		const Clause &clause = clauseDB[watcher.clauseIdx];
		if ( clause.removed || clause.literals.size() != 2 ) continue;
		const int implied = watcher.blocker;
		if ( Value(implied) == 1 && mark[abs(implied)] == time_stamp ) {
			mark[abs(implied)] = 0;
		}
	}
	size_t end = learnt.size();
	for ( size_t i = 1; i < end; ) {
		if ( mark[abs(learnt[i])] == time_stamp ) i ++;
		else {
			std::swap(learnt[i], learnt[-- end]);
			minimizedLiterals ++;
		}
	}
	learnt.resize(end);
}

// First-UIP analysis, recursive minimization, binary resolution, and LBD bump.
int Solver::analyze( int conflict, int &backtrackLevel, int &lbd ) {
	if ( conflict < 0 || conflict >= static_cast<int>(clauseDB.size()) ) return 30;
	const int conflictLevel = static_cast<int>(decVarInTrail.size());
	if ( conflictLevel == 0 ) return 20;
	nextAnalysisStamp();
	learnt.clear();
	learnt.push_back(0);
	lastDecisionLevel.clear();
	int unresolved = 0;
	int resolveLiteral = 0;
	int trailIndex = static_cast<int>(trail.size()) - 1;
	do {
		if ( conflict < 0 || conflict >= static_cast<int>(clauseDB.size()) ) return 30;
		updateClauseQuality(conflict);
		const Clause &clause = clauseDB[conflict];
		for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
			const int literal = clause.literals[i];
			const int variable = abs(literal);
			if ( variable == abs(resolveLiteral) || mark[variable] == time_stamp ||
			     level[variable] == 0 ) continue;
			update_score(variable, 1.0);
			forceUNSAT[variable] = literal > 0 ? -1 : 1;
			mark[variable] = time_stamp;
			if ( level[variable] == conflictLevel ) {
				unresolved ++;
				if ( reason[variable] >= 0 && clauseDB[reason[variable]].learntClause ) {
					lastDecisionLevel.push_back(variable);
				}
			} else learnt.push_back(literal);
		}
		while ( trailIndex >= 0 && mark[abs(trail[trailIndex])] != time_stamp ) trailIndex --;
		if ( trailIndex < 0 || unresolved == 0 ) return 30;
		resolveLiteral = trail[trailIndex --];
		mark[abs(resolveLiteral)] = 0;
		unresolved --;
		conflict = reason[abs(resolveLiteral)];
	} while ( unresolved > 0 );
	learnt[0] = -resolveLiteral;

	analyzeToClear.clear();
	nextAnalysisStamp();
	uint32_t abstractLevels = 0;
	for ( size_t i = 0; i < learnt.size(); i ++ ) {
		mark[abs(learnt[i])] = time_stamp;
		if ( i != 0 ) abstractLevels |= UINT32_C(1) << (level[abs(learnt[i])] & 31);
	}
	size_t out = 1;
	for ( size_t i = 1; i < learnt.size(); i ++ ) {
		if ( reason[abs(learnt[i])] >= 0 && literalRedundant(learnt[i], abstractLevels) ) {
			minimizedLiterals ++;
		} else learnt[out ++] = learnt[i];
	}
	learnt.resize(out);
	binaryMinimization();

	lbd = calculateLBD(learnt);
	if ( lbd_queue_size < 50 ) lbd_queue_size ++;
	else fast_lbd_sum -= lbd_queue[lbd_queue_pos];
	lbd_queue[lbd_queue_pos ++] = lbd;
	if ( lbd_queue_pos == 50 ) lbd_queue_pos = 0;
	fast_lbd_sum += lbd;
	slow_lbd_sum += lbd;

	backtrackLevel = 0;
	if ( learnt.size() > 1 ) {
		size_t maxIndex = 1;
		for ( size_t i = 2; i < learnt.size(); i ++ ) {
			if ( level[abs(learnt[i])] > level[abs(learnt[maxIndex])] ) maxIndex = i;
		}
		std::swap(learnt[1], learnt[maxIndex]);
		backtrackLevel = level[abs(learnt[1])];
	}
	for ( size_t i = 0; i < lastDecisionLevel.size(); i ++ ) {
		const int variable = lastDecisionLevel[i];
		if ( clauseDB[reason[variable]].lbd < lbd ) update_score(variable, 1.0);
	}
	return 0;
}

// Full phase saving and non-chronological backtracking.
void Solver::backtrack( int backtrackLevel ) {
	if ( static_cast<int>(decVarInTrail.size()) <= backtrackLevel ) return;
	const int trailLimit = decVarInTrail[backtrackLevel];
	for ( int i = static_cast<int>(trail.size()) - 1; i >= trailLimit; i -- ) {
		const int variable = abs(trail[i]);
		saved[variable] = trail[i] > 0 ? 1 : -1;
		value[variable] = 0;
		reason[variable] = -1;
		level[variable] = 0;
		if ( !eliminated[variable] && !vsids.inHeap(variable) ) vsids.insert(variable);
	}
	propagated = trailLimit;
	trail.resize(trailLimit);
	decVarInTrail.resize(backtrackLevel);
}

void Solver::clearLBDQueue() {
	fast_lbd_sum = 0;
	lbd_queue_size = lbd_queue_pos = 0;
}

void Solver::pushTrailSize() {
	if ( trail_queue_size < 5000 ) trail_queue_size ++;
	else trailQueueSum -= trail_queue[trail_queue_pos];
	trail_queue[trail_queue_pos ++] = static_cast<int>(trail.size());
	if ( trail_queue_pos == 5000 ) trail_queue_pos = 0;
	trailQueueSum += trail.size();
	if ( conflictsRestarts > 10000 && lbd_queue_size == 50 &&
	     trail.size() > 1.4 * (trailQueueSum / trail_queue_size) ) {
		clearLBDQueue();
		blockedRestarts ++;
	}
}

bool Solver::shouldRestart( uint64_t searchConflicts, uint64_t conflictBudget ) {
	if ( lubyRestart ) return searchConflicts >= conflictBudget;
	if ( lbd_queue_size != 50 || conflictsRestarts == 0 ) return false;
	const uint64_t recentAverage = static_cast<uint64_t>(fast_lbd_sum) / lbd_queue_size;
	return 0.8 * recentAverage > slow_lbd_sum / conflictsRestarts;
}

static double nextRandom( double &seed ) {
	seed *= 1389796;
	const int quotient = static_cast<int>(seed / 2147483647);
	seed -= static_cast<double>(quotient) * 2147483647;
	return seed / 2147483647;
}

void Solver::restart() {
	clearLBDQueue();
	newDescent = true;
	if ( randomizeOnRestarts ) {
		// Scale before conversion: the upstream unscaled cast always yielded zero.
		randomDescentAssignments = static_cast<uint32_t>(nextRandom(randomSeed) * 4294967296.0);
	}
	backtrack(0);
	restarts ++;
}

uint64_t Solver::luby( uint64_t index ) {
	uint64_t size = 1;
	unsigned int exponent = 0;
	while ( size <= index && size <= (UINT64_MAX - 1) / 2 ) {
		size = 2 * size + 1;
		exponent ++;
	}
	while ( size - 1 != index ) {
		size = (size - 1) / 2;
		if ( size == 0 ) return 1;
		exponent --;
		index %= size;
	}
	return UINT64_C(1) << exponent;
}

// Rebuild watches after structural edits while preserving the active trail.
void Solver::rebuildWatches() {
	for ( int i = 0; i <= 2 * vars; i ++ ) watched_literals[i].clear();
	for ( int i = 0; i < static_cast<int>(clauseDB.size()); i ++ ) {
		Clause &clause = clauseDB[i];
		if ( clause.removed || clause.literals.size() < 2 ) continue;
		WatchedLiterals(-clause[0]).push_back(WL(i, clause[1]));
		WatchedLiterals(-clause[1]).push_back(WL(i, clause[0]));
	}
}

void Solver::compactClauses() {
	reduceMap.assign(clauseDB.size(), -1);
	int out = 0;
	origin_clauses = 0;
	ordinaryLearntCount = 0;
	for ( int i = 0; i < static_cast<int>(clauseDB.size()); i ++ ) {
		if ( clauseDB[i].removed ) continue;
		if ( !clauseDB[i].learntClause && !clauseDB[i].permanent ) origin_clauses ++;
		if ( clauseDB[i].learntClause && !clauseDB[i].permanent ) ordinaryLearntCount ++;
		reduceMap[i] = out;
		if ( out != i ) clauseDB[out] = std::move(clauseDB[i]);
		out ++;
	}
	clauseDB.erase(clauseDB.begin() + out, clauseDB.end());
	for ( size_t i = 0; i < trail.size(); i ++ ) {
		const int literal = trail[i];
		int &cref = reason[abs(literal)];
		if ( cref >= 0 ) cref = reduceMap[cref];
	}
	rebuildWatches();
}

// Root BCP, satisfied-clause removal, and falsified-literal cleanup.
bool Solver::simplifyRoot() {
	if ( !decVarInTrail.empty() ) return false;
	while ( true ) {
		if ( propagate() != -1 ) return false;
		bool changed = false;
		bool assigned = false;
		for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
			Clause &clause = clauseDB[i];
			if ( clause.removed ) continue;
			bool satisfied = false;
			for ( size_t j = 0; j < clause.literals.size(); j ++ ) {
				const int literal = clause.literals[j];
				if ( Value(literal) == 1 ) {
					satisfied = true;
					break;
				}
			}
			if ( satisfied ) {
				clause.removed = true;
				changed = true;
				continue;
			}
			size_t out = 0;
			for ( size_t j = 0; j < clause.literals.size(); j ++ ) {
				const int literal = clause.literals[j];
				if ( Value(literal) != -1 ) clause[out ++] = literal;
			}
			if ( out == 0 ) return false;
			if ( out != clause.literals.size() ) {
				clause.literals.resize(out);
				changed = true;
			}
			if ( out == 1 ) {
				assign(clause[0], 0, -1);
				clause.removed = true;
				assigned = changed = true;
			}
		}
		if ( changed ) compactClauses();
		if ( !assigned ) break;
	}
	simpDBAssigns = static_cast<int>(trail.size());
	simpDBProps = 0;
	for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
		const Clause &clause = clauseDB[i];
		if ( clause.literals.size() <= static_cast<uint64_t>(INT64_MAX - simpDBProps) ) {
			simpDBProps += clause.literals.size();
		} else simpDBProps = INT64_MAX;
	}
	vsids.initialize(activity, vars);
	for ( int variable = 1; variable <= vars; variable ++ ) {
		if ( !eliminated[variable] && value[variable] == 0 ) vsids.insert(variable);
	}
	return true;
}

struct ClauseRank {
	int index;
	int lbd;
	double activity;
	bool binary;
};

static bool lowerActivity( const ClauseRank &first, const ClauseRank &second ) {
	if ( first.binary != second.binary ) return !first.binary;
	if ( first.binary ) return false;
	return first.activity < second.activity;
}

static bool lowerQuality( const ClauseRank &first, const ClauseRank &second ) {
	if ( first.binary != second.binary ) return !first.binary;
	if ( first.binary ) return false;
	if ( first.lbd != second.lbd ) return first.lbd > second.lbd;
	return first.activity < second.activity;
}

// Protect all current reasons and apply Glucose's full-learnt-set deletion limit.
void Solver::reduce() {
	std::vector<ClauseRank> ranks;
	for ( int i = 0; i < static_cast<int>(clauseDB.size()); i ++ ) {
		const Clause &clause = clauseDB[i];
		if ( clause.learntClause && !clause.permanent && !clause.removed ) {
			ranks.push_back({i, clause.lbd, clause.activity, clause.literals.size() == 2});
		}
	}
	if ( ranks.empty() ) return;
	reductionRuns ++;
	reduces ++;
	std::vector<uint8_t> locked(clauseDB.size(), 0);
	for ( size_t i = 0; i < trail.size(); i ++ ) {
		const int literal = trail[i];
		if ( reason[abs(literal)] >= 0 ) locked[reason[abs(literal)]] = 1;
	}
	std::sort(ranks.begin(), ranks.end(), lowerActivity);
	if ( !chanseokStrategy ) {
		for ( size_t i = ranks.size() * 90 / 100; i < ranks.size(); i ++ ) {
			clauseDB[ranks[i].index].removable = false;
		}
		std::sort(ranks.begin(), ranks.end(), lowerQuality);
		if ( ranks[ranks.size() / 2].lbd <= 3 ) nbclausesbeforereduce += specialIncReduceDB;
		if ( ranks.back().lbd <= 5 ) nbclausesbeforereduce += specialIncReduceDB;
	}
	size_t limit = ranks.size() / 2;
	for ( size_t i = 0; i < ranks.size(); i ++ ) {
		Clause &clause = clauseDB[ranks[i].index];
		if ( clause.lbd > 2 && clause.literals.size() > 2 && clause.removable &&
		     !locked[ranks[i].index] && i < limit ) {
			clause.removed = true;
			deletedClauses ++;
		} else {
			if ( !clause.removable ) limit ++;
			clause.removable = true;
		}
	}
	compactClauses();
}

// Glucose 4.2.1's four independent automatic strategy tests.
void Solver::adaptSolver() {
	bool adjusted = false;
	bool reinitialize = false;
	const float decisionsPerConflict = conflicts == 0 ? 0.0f :
		static_cast<float>(decides) / static_cast<float>(conflicts);
	if ( decisionsPerConflict <= 1.2f ) {
		chanseokStrategy = true;
		coLBDBound = 4;
		glureduce = true;
		adjusted = reinitialize = true;
		firstReduceDB = nbclausesbeforereduce = 2000;
		curRestart = conflicts / nbclausesbeforereduce + 1;
		incReduceDB = 0;
	}
	if ( noDecisionConflict < 30000 ) {
		lubyRestart = true;
		var_decay = max_var_decay = 0.999;
		adjusted = true;
	}
	if ( noDecisionConflict > 54400 ) {
		chanseokStrategy = glureduce = true;
		coLBDBound = 3;
		firstReduceDB = 30000;
		var_decay = max_var_decay = 0.99;
		randomizeOnRestarts = true;
		adjusted = true;
	}
	if ( learntGlue > learntBinary && learntGlue - learntBinary > 20000 ) {
		var_decay = max_var_decay = 0.91;
		adjusted = true;
	}
	if ( adjusted ) {
		clearLBDQueue();
		slow_lbd_sum = 0;
		conflictsRestarts = 0;
	}
	if ( chanseokStrategy && adjusted ) {
		for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
			Clause &clause = clauseDB[i];
			if ( clause.learntClause && !clause.permanent && clause.lbd <= coLBDBound ) {
				clause.permanent = true;
				if ( ordinaryLearntCount > 0 ) ordinaryLearntCount --;
			}
		}
	}
	if ( reinitialize ) {
		for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
			Clause &clause = clauseDB[i];
			if ( clause.learntClause && !clause.permanent ) clause.removed = true;
		}
		compactClauses();
	}
}

bool Solver::withinBudget() const {
	return cpuDeadline <= 0.0 || timeCheckerCPU() < cpuDeadline;
}

// Preprocess once; perform queued LCM at the next search entry.
int Solver::solve() {
	int result = 0;
	const double processStart = timeCheckerCPU();
	double timeLimit = 2000.0;
	const char *env = getenv("UATU_TIMEOUT_SEC");
	if ( env != nullptr ) {
		const double parsed = atof(env);
		if ( parsed > 0.0 ) timeLimit = parsed;
	}
	cpuDeadline = processStart + timeLimit;
	if ( !preprocessingDone ) {
		result = preprocess();
		preprocessingDone = true;
	}
	ordinaryLearntCount = 0;
	for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
		const Clause &clause = clauseDB[i];
		if ( clause.learntClause && !clause.permanent && !clause.removed ) ordinaryLearntCount ++;
	}
	bool searchEntry = true;
	bool decisionWasMade = false;
	uint64_t searchConflicts = 0;
	uint64_t searchIndex = 0;
	uint64_t conflictBudget = 0;
	uint64_t loopCounter = 0;
	while ( result == 0 ) {
		if ( (loopCounter ++ & 4095) == 0 && !withinBudget() ) {
			result = 30;
			break;
		}
		if ( searchEntry ) {
			searchConflicts = 0;
			decisionWasMade = false;
			const uint64_t sequence = luby(searchIndex);
			conflictBudget = sequence <= UINT64_MAX / 100 ? sequence * 100 : UINT64_MAX;
			if ( performLCM ) {
				result = vivifyLearnts();
				performLCM = false;
				if ( result != 0 ) break;
			}
			searchEntry = false;
		}
		const int conflict = propagate();
		if ( conflict != -1 ) {
			newDescent = false;
			if ( !decisionWasMade ) noDecisionConflict ++;
			decisionWasMade = false;
			conflicts ++;
			searchConflicts ++;
			conflictsRestarts ++;
			if ( conflicts % 5000 == 0 && var_decay < max_var_decay ) {
				var_decay = std::min(var_decay + 0.01, max_var_decay);
			}
			if ( decVarInTrail.empty() ) {
				result = 20;
				break;
			}
			if ( adaptStrategies && conflicts == 100000 ) {
				backtrack(0);
				adaptSolver();
				adaptStrategies = false;
				searchEntry = true;
				searchIndex ++;
				continue;
			}
			pushTrailSize();
			int backtrackLevel = 0;
			int lbd = 0;
			result = analyze(conflict, backtrackLevel, lbd);
			if ( result != 0 ) break;
			backtrack(backtrackLevel);
			if ( learnt.size() == 1 ) assign(learnt[0], 0, -1);
			else {
				const int cref = add_clause(learnt);
				Clause &clause = clauseDB[cref];
				clause.lbd = lbd;
				if ( chanseokStrategy && lbd <= coLBDBound ) clause.permanent = true;
				else {
					clause.learntClause = true;
					ordinaryLearntCount ++;
					bumpClauseActivity(cref);
				}
				if ( lbd <= 2 ) learntGlue ++;
				if ( learnt.size() == 2 ) learntBinary ++;
				assign(learnt[0], backtrackLevel, cref);
			}
			var_inc /= var_decay;
			clause_inc /= clause_decay;
		} else {
			if ( shouldRestart(searchConflicts, conflictBudget) ) {
				restart();
				searchEntry = true;
				searchIndex ++;
				continue;
			}
			if ( decVarInTrail.empty() && simpDBAssigns != static_cast<int>(trail.size()) &&
			     simpDBProps <= 0 && !simplifyRoot() ) {
				result = 20;
				break;
			}
			const bool reductionDue = glureduce && nbclausesbeforereduce != 0 &&
				conflicts / nbclausesbeforereduce >= curRestart;
			if ( reductionDue || (chanseokStrategy && !glureduce) ) {
				if ( ordinaryLearntCount > 0 && (glureduce || ordinaryLearntCount > firstReduceDB) ) {
					curRestart = conflicts / nbclausesbeforereduce + 1;
					reduce();
					performLCM = true;
					nbclausesbeforereduce += incReduceDB;
				}
			}
			result = decide();
			decisionWasMade = result == 0;
		}
	}
	if ( result == 10 && !extendModel() ) result = 30;
	processTimeFinal = timeCheckerCPU() - processStart;
	printf( "Elapsed Time [Total] (CPU): %.4f\n", processTimeFinal );
#if UATU_PROFILE_BCP
	printf( "Elapsed Time [Propa] (wall): %.4f\n", propagaTimeFinal );
	printf( "Elapsed Time [MaxBCP] (wall): %.4f\n", maxBCPTime );
#endif
	printf( "----------------------------------------------------\n" );
	fflush( stdout );
	return result;
}

void Solver::printModel() {
	for ( int i = 1; i <= vars; i ++ ) printf( "%d ", value[i] * i );
	printf( "0\n" );
}
