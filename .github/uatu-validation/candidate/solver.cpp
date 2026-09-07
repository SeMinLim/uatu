#include "solver.h"
#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <utility>


#ifndef UATU_PROFILE_BCP
#define UATU_PROFILE_BCP 0
#endif


//// Required functions
// Elapsed time checker
static inline double timeCheckerCPU( void ) {
        struct rusage ru;
        getrusage(RUSAGE_SELF, &ru);

	return (double)ru.ru_utime.tv_sec + (double)ru.ru_utime.tv_usec / 1000000;
}

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

// Keep clause identifiers stable while ranking the learnt database.
struct ClauseRank {
	int clauseIdx;
	int lbd;
	size_t size;
	double activity;
};

static bool higherClauseActivity( const ClauseRank &a, const ClauseRank &b ) {
	if ( a.activity != b.activity ) return a.activity > b.activity;
	return a.clauseIdx < b.clauseIdx;
}

static bool worseClauseLBD( const ClauseRank &a, const ClauseRank &b ) {
	const bool aBinary = a.size == 2;
	const bool bBinary = b.size == 2;
	if ( aBinary != bBinary ) return !aBinary;
	if ( a.lbd != b.lbd ) return a.lbd > b.lbd;
	if ( a.activity != b.activity ) return a.activity < b.activity;
	return a.clauseIdx < b.clauseIdx;
}

//// Solver
// Release partially initialized arrays as well as successfully parsed formulas.
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

// Allocate memory and initialize the values
void Solver::initialize( void ) {
        value = new int8_t[vars + 1];
        local_best = new int8_t[vars + 1];
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
	minimizeStack.reserve(64);
	minimizeTouched.reserve(64);

        conflicts = decides = unitPropagations = bcpFunctionCalls = 0;
        restarts = rephases = reduces = 0;
	blockedRestarts = varDecayUpdates = 0;
	trail_queue_size = trail_queue_pos = 0;
	trail_queue_sum = 0;
        reductionRuns = 0;
        deletedClauses = minimizedLiterals = 0;
        clauseActivityBumps = dynamicLBDUpdates = 0;
        threshold = propagated = time_stamp = 0;
        lbdStamp = 0;
        fast_lbd_sum = lbd_queue_size = lbd_queue_pos = slow_lbd_sum = 0;
        processTimeFinal = propagaTimeFinal = maxBCPTime = 0.0;

        var_inc = 1;
        var_decay = 0.8;
        clause_inc = 1.0;
        clause_decay = 0.999;
        if ( const char *env = getenv("UATU_CLAUSE_DECAY") ) {
                const double parsed = atof(env);
                if ( parsed > 0.0 && parsed < 1.0 ) clause_decay = parsed;
        }
        rephase_inc = 100000;
        rephase_limit = 100000;
        reduce_limit = 8192;

        vsids.initialize(activity, vars);
        value[0] = local_best[0] = saved[0] = 0;
        reason[0] = -1;
        level[0] = mark[0] = 0;
        lbdMark[0] = 0;
        activity[0] = 0.0;
        for ( int i = 1; i <= vars; i ++ ) {
                value[i] = local_best[i] = saved[i] = 0;
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
        ++bcpFunctionCalls;
#if UATU_PROFILE_BCP
        using BcpClock = std::chrono::steady_clock;
        const auto bcpStart = BcpClock::now();
        auto finishBcpTiming = [&]() {
                const double seconds =
                        std::chrono::duration<double>(BcpClock::now() - bcpStart).count();
                propagaTimeFinal += seconds;
                if ( seconds > maxBCPTime ) maxBCPTime = seconds;
        };
#endif

        while ( propagated < static_cast<int>(trail.size()) ) {
                const int p = trail[propagated++];
                std::vector<WL> &ws = WatchedLiterals(p);
                const int numClauses = static_cast<int>(ws.size());
                int out = 0;

                for ( int i = 0; i < numClauses; ) {
                        const int blocker = ws[i].blocker;
                        if ( Value(blocker) == 1 ) {
                                ws[out++] = ws[i++];
                                continue;
                        }

                        const int cref = ws[i].clauseIdx;
                        Clause &c = clauseDB[cref];
                        const int falseLiteral = -p;
                        if ( c[0] == falseLiteral ) {
                                c[0] = c[1];
                                c[1] = falseLiteral;
                        }
                        ++i;

                        const int firstWatch = c[0];
                        const WL watcher(cref, firstWatch);
                        if ( Value(firstWatch) == 1 ) {
                                ws[out++] = watcher;
                                continue;
                        }

                        int k = 2;
                        const int size = static_cast<int>(c.literals.size());
                        while ( k < size && Value(c[k]) == -1 ) ++k;

                        if ( k < size ) {
                                c[1] = c[k];
                                c[k] = falseLiteral;
                                WatchedLiterals(-c[1]).push_back(watcher);
                        } else {
                                ws[out++] = watcher;
                                if ( Value(firstWatch) == -1 ) {
                                        while ( i < numClauses ) ws[out++] = ws[i++];
                                        ws.resize(out);
#if UATU_PROFILE_BCP
                                        finishBcpTiming();
#endif
                                        return cref;
                                }

                                assign(firstWatch, level[abs(p)], cref);
                                ++unitPropagations;
                        }
                }
                ws.resize(out);
        }

#if UATU_PROFILE_BCP
        finishBcpTiming();
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
		fprintf( stderr, "failed to read DIMACS input\n" );
		return 30;
	}
	if ( !haveHeader || !buffer.empty() || parsedClauses != clauses ) return invalidCNF();
	origin_clauses = static_cast<int>(clauseDB.size());
	if ( contradictory ) return 20;
	return propagate() == -1 ? 0 : 20;
}

// Pick decision variable based on VSIDS
int Solver::decide( void ) {
	// Pop VSIDS max-heap until finding an undefined literal
    	int next = -1;
	while ( next == -1 || Value(next) != 0 ) {
        	if ( vsids.empty() ) return 10;
        	else next = vsids.pop();
    	}

	// Save the decision variable's position in trail
    	decVarInTrail.push_back(trail.size());

	// If there's saved one (polarity), use that
	if ( saved[next] ) next *= saved[next];

	// Assign
    	assign(next, decVarInTrail.size(), -1);

	// Parameter update
    	decides ++;

	return 0;
}

// Update variable activity
void Solver::update_score( int var, double coeff ) {
	// Update score and prevent overflow
	// Double type bumping scheme
	if ( (activity[var] += var_inc * coeff) > 1e100 ) {
		for ( int i = 1; i <= vars; i ++ ) activity[i] *= 1e-100;
		var_inc *= 1e-100;
	}

	// Update Heap
    	if ( vsids.inHeap(var) ) vsids.update(var);
}

// Update learnt-clause activity
void Solver::bumpClauseActivity( int cref ) {
        if ( cref < origin_clauses || cref >= static_cast<int>(clauseDB.size()) ) return;

        Clause &clause = clauseDB[cref];
        clause.activity += clause_inc;
        if ( clause.useCount != UINT32_MAX ) clause.useCount ++;
        clauseActivityBumps ++;

        if ( clause.activity > 1e100 ) {
                for ( int i = origin_clauses; i < static_cast<int>(clauseDB.size()); i ++ ) {
                        clauseDB[i].activity *= 1e-100;
                }
                clause_inc *= 1e-100;
        }
}

// Calculate LBD with the current decision-level assignment
int Solver::calculateClauseLBD( const Clause &clause ) {
        lbdStamp ++;
        if ( lbdStamp == 0 ) {
                for ( int i = 0; i <= vars; i ++ ) lbdMark[i] = 0;
                lbdStamp = 1;
        }

        int currentLBD = 0;
        for ( int literal : clause.literals ) {
                const int decisionLevel = level[abs(literal)];
                if ( decisionLevel > 0 && lbdMark[decisionLevel] != lbdStamp ) {
                        lbdMark[decisionLevel] = lbdStamp;
                        currentLBD ++;
                }
        }

        return currentLBD;
}

// Update learnt-clause usage and dynamic LBD
void Solver::updateClauseQuality( int cref ) {
	if ( cref < origin_clauses || cref >= static_cast<int>(clauseDB.size()) ) return;

	bumpClauseActivity(cref);

	Clause &clause = clauseDB[cref];
	if ( clause.lbd <= GLUE_LBD ) return;

	const int currentLBD = calculateClauseLBD(clause);
	if ( currentLBD > 0 && currentLBD + 1 < clause.lbd ) {
		if ( clause.lbd <= LBD_PROTECTION_MAX ) clause.canBeDeleted = false;
		clause.lbd = currentLBD;
		dynamicLBDUpdates ++;
	}
}

// Follow reason chains with explicit storage and roll back unsuccessful proofs.
bool Solver::isLearntLiteralRedundant( int variable, uint32_t abstractLevels,
                                      uint32_t membershipStamp ) {
	const size_t touchedStart = minimizeTouched.size();
	minimizeStack.clear();
	minimizeStack.push_back(variable);
	bool redundant = true;

	while ( !minimizeStack.empty() && redundant ) {
		const int current = minimizeStack.back();
		minimizeStack.pop_back();
		const int reasonClause = reason[current];
		if ( reasonClause < 0 || reasonClause >= static_cast<int>(clauseDB.size()) ) {
			redundant = false;
			break;
		}

		const Clause &reasonData = clauseDB[reasonClause];
		for ( size_t i = 0; i < reasonData.literals.size(); i ++ ) {
			const int other = abs(reasonData.literals[i]);
			if ( other == current || level[other] == 0 ||
			     mark[other] == membershipStamp ) continue;

			// Level-bit collisions only permit extra traversal, never deletion.
			const uint32_t levelBit = uint32_t(1) << (level[other] & 31);
			const int otherReason = reason[other];
			if ( (abstractLevels & levelBit) == 0 || otherReason < 0 ||
			     otherReason >= static_cast<int>(clauseDB.size()) ) {
				redundant = false;
				break;
			}

			mark[other] = membershipStamp;
			minimizeTouched.push_back(other);
			minimizeStack.push_back(other);
		}
	}

	if ( !redundant ) {
		for ( size_t i = touchedStart; i < minimizeTouched.size(); i ++ ) {
			mark[minimizeTouched[i]] = 0;
		}
		minimizeTouched.resize(touchedStart);
	}
	minimizeStack.clear();
	return redundant;
}

// Prove redundancy through the implication graph while retaining the UIP.
void Solver::minimizeLearntRecursive() {
	if ( learnt.size() <= 1 ) return;

	nextAnalysisStamp();
	const uint32_t membershipStamp = time_stamp;
	uint32_t abstractLevels = 0;
	minimizeTouched.clear();

	for ( size_t i = 0; i < learnt.size(); i ++ ) {
		const int variable = abs(learnt[i]);
		mark[variable] = membershipStamp;
		if ( i != 0 ) abstractLevels |= uint32_t(1) << (level[variable] & 31);
	}

	// Original membership remains valid as removed literals are themselves redundant.
	size_t out = 1;
	for ( size_t i = 1; i < learnt.size(); i ++ ) {
		const int literal = learnt[i];
		const int variable = abs(literal);
		const int reasonClause = reason[variable];
		if ( reasonClause >= 0 && reasonClause < static_cast<int>(clauseDB.size()) &&
		     isLearntLiteralRedundant(variable, abstractLevels, membershipStamp) ) {
			minimizedLiterals ++;
		} else {
			learnt[out] = literal;
			out ++;
		}
	}
	learnt.resize(out);
	minimizeTouched.clear();
}

// Resolve (p OR q OR rest) with a binary (p OR NOT q), preserving the UIP p.
void Solver::minimizeLearntBinary() {
	if ( learnt.size() <= 1 || learnt.size() > BINARY_MINIMIZATION_MAX_SIZE ) return;

	nextAnalysisStamp();
	int currentLBD = 0;
	for ( size_t i = 0; i < learnt.size(); i ++ ) {
		const int decisionLevel = level[abs(learnt[i])];
		if ( decisionLevel > 0 && mark[decisionLevel] != time_stamp ) {
			mark[decisionLevel] = time_stamp;
			currentLBD ++;
			if ( currentLBD > BINARY_MINIMIZATION_MAX_LBD ) return;
		}
	}

	nextAnalysisStamp();
	const uint32_t membershipStamp = time_stamp;
	for ( size_t i = 1; i < learnt.size(); i ++ ) {
		mark[abs(learnt[i])] = membershipStamp;
	}

	const int assertingLiteral = learnt[0];
	const std::vector<WL> &watchers = WatchedLiterals(-assertingLiteral);
	for ( size_t i = 0; i < watchers.size(); i ++ ) {
		const int blocker = watchers[i].blocker;
		if ( mark[abs(blocker)] != membershipStamp || Value(blocker) != 1 ) continue;

		const int cref = watchers[i].clauseIdx;
		if ( cref < 0 || cref >= static_cast<int>(clauseDB.size()) ) continue;
		const Clause &clause = clauseDB[cref];
		if ( clause.literals.size() != 2 ) continue;

		int otherLiteral = 0;
		if ( clause.literals[0] == assertingLiteral ) otherLiteral = clause.literals[1];
		else if ( clause.literals[1] == assertingLiteral ) otherLiteral = clause.literals[0];
		else continue;

		// Every learnt literal is false; the true binary partner has opposite polarity.
		const int other = abs(otherLiteral);
		if ( mark[other] == membershipStamp && Value(otherLiteral) == 1 ) mark[other] = 0;
	}

	size_t out = 1;
	for ( size_t i = 1; i < learnt.size(); i ++ ) {
		if ( mark[abs(learnt[i])] == membershipStamp ) {
			learnt[out] = learnt[i];
			out ++;
		} else {
			minimizedLiterals ++;
		}
	}
	learnt.resize(out);
}

// Conflict analysis
int Solver::analyze( int conflict, int &backtrackLevel, int &lbd ) {
        nextAnalysisStamp();
        learnt.clear();

        if ( conflict < 0 || conflict >= static_cast<int>(clauseDB.size()) ) {
                fprintf( stderr, "internal error: invalid conflict clause\n" );
                return 30;
        }

        const int conflictLevel = static_cast<int>(decVarInTrail.size());
        if ( conflictLevel == 0 ) return 20;

        learnt.push_back(0);
        int unresolved = 0;
        int resolveLiteral = 0;
        int trailIndex = static_cast<int>(trail.size()) - 1;
        std::vector<int> bump;
        bump.reserve(32);

        do {
                if ( conflict < 0 || conflict >= static_cast<int>(clauseDB.size()) ) {
                        fprintf( stderr, "internal error: invalid reason clause\n" );
                        return 30;
                }

                updateClauseQuality(conflict);
                Clause &clause = clauseDB[conflict];
                const int begin = resolveLiteral == 0 ? 0 : 1;
                for ( int i = begin; i < static_cast<int>(clause.literals.size()); i ++ ) {
                        const int variable = abs(clause[i]);
                        if ( mark[variable] == time_stamp || level[variable] == 0 ) continue;

                        update_score(variable, 0.5);
                        bump.push_back(variable);
                        mark[variable] = time_stamp;

                        if ( level[variable] == conflictLevel ) ++unresolved;
                        else learnt.push_back(clause[i]);
                }

                while ( trailIndex >= 0 &&
                        mark[abs(trail[trailIndex])] != time_stamp ) --trailIndex;
                if ( trailIndex < 0 ) {
                        fprintf( stderr, "internal error: malformed implication graph\n" );
                        return 30;
                }

                resolveLiteral = trail[trailIndex --];
                mark[abs(resolveLiteral)] = 0;
                --unresolved;

                if ( unresolved > 0 ) {
                        const int nextReason = reason[abs(resolveLiteral)];
                        if ( nextReason < 0 ||
                             nextReason >= static_cast<int>(clauseDB.size()) ) {
                                fprintf( stderr, "internal error: invalid reason clause\n" );
                                return 30;
                        }
                        conflict = nextReason;
                }
        } while ( unresolved > 0 );

        learnt[0] = -resolveLiteral;

	minimizeLearntRecursive();
	minimizeLearntBinary();

        nextAnalysisStamp();
        lbd = 0;
        for ( int literal : learnt ) {
                const int decisionLevel = level[abs(literal)];
                if ( decisionLevel && mark[decisionLevel] != time_stamp ) {
                        mark[decisionLevel] = time_stamp;
                        ++lbd;
                }
        }

        if ( lbd_queue_size < 50 ) ++lbd_queue_size;
        else fast_lbd_sum -= lbd_queue[lbd_queue_pos];
        lbd_queue[lbd_queue_pos ++] = lbd;
        if ( lbd_queue_pos == 50 ) lbd_queue_pos = 0;
        fast_lbd_sum += lbd;
        slow_lbd_sum += lbd;

        if ( learnt.size() == 1 ) {
                backtrackLevel = 0;
        } else {
                int maxIndex = 1;
                for ( int i = 2; i < static_cast<int>(learnt.size()); i ++ ) {
                        if ( level[abs(learnt[i])] > level[abs(learnt[maxIndex])] ) {
                                maxIndex = i;
                        }
                }
                std::swap(learnt[1], learnt[maxIndex]);
                backtrackLevel = level[abs(learnt[1])];
        }

        // Original second-stage bump retained after the ablation trial.
        for ( int variable : bump ) {
                if ( level[variable] >= backtrackLevel - 1 ) update_score(variable, 1.0);
        }

        return 0;
}

// Backtracking
void Solver::backtrack( int backtrackLevel ) {
        if ( static_cast<int>(decVarInTrail.size()) <= backtrackLevel ) return;

        const int trailLimit = decVarInTrail[backtrackLevel];
        for ( int i = static_cast<int>(trail.size()) - 1; i >= trailLimit; i -- ) {
                const int variable = abs(trail[i]);

                saved[variable] = trail[i] > 0 ? 1 : -1;
                value[variable] = 0;
                reason[variable] = -1;
                level[variable] = 0;

                if ( !vsids.inHeap(variable) ) vsids.insert(variable);
        }

        propagated = trailLimit;
        trail.resize(propagated);
        decVarInTrail.resize(backtrackLevel);
}

// Delay LBD restarts while conflict-time assignments are unusually deep.
void Solver::updateRestartBlocking() {
	const int trailSize = static_cast<int>(trail.size());
	if ( trail_queue_size < RESTART_TRAIL_WINDOW ) trail_queue_size ++;
	else trail_queue_sum -= static_cast<uint64_t>(trail_queue[trail_queue_pos]);
	trail_queue[trail_queue_pos] = trailSize;
	trail_queue_sum += static_cast<uint64_t>(trailSize);
	trail_queue_pos ++;
	if ( trail_queue_pos == RESTART_TRAIL_WINDOW ) trail_queue_pos = 0;

	// conflicts counts completed analyses; this conflict is the next one.
	if ( conflicts < RESTART_BLOCKING_START || lbd_queue_size != 50 ||
	     trail_queue_size != RESTART_TRAIL_WINDOW ) return;
	const double averageTrail = static_cast<double>(trail_queue_sum) / trail_queue_size;
	if ( trailSize <= RESTART_BLOCKING_FACTOR * averageTrail ) return;

	fast_lbd_sum = 0;
	lbd_queue_size = 0;
	lbd_queue_pos = 0;
	blockedRestarts ++;
}

// Gradually retain a longer VSIDS activity history.
void Solver::updateVSIDSDecay() {
	if ( conflicts == 0 || conflicts % VSIDS_DECAY_INTERVAL != 0 ||
	     var_decay >= VSIDS_DECAY_MAX ) return;
	var_decay = std::min(VSIDS_DECAY_MAX, var_decay + 0.01);
	varDecayUpdates ++;
}

// Restart from the root while retaining learnt clauses and saved phases.
void Solver::restart() {
	backtrack(0);
	fast_lbd_sum = 0;
	lbd_queue_size = 0;
	lbd_queue_pos = 0;
	restarts ++;
}

// Rephase from the root.
void Solver::rephase() {
	// Finish ordinary phase saving before installing the new phase targets.
	backtrack(0);

	// Retain V3's phase-selection sequence and conflict-based schedule.
	if ( rephases / 2 == 1 ) {
		for ( int i = 1; i <= vars; i ++ ) saved[i] = local_best[i];
	} else {
		for ( int i = 1; i <= vars; i ++ ) saved[i] = -local_best[i];
	}

	if ( rephase_inc <= UINT64_MAX / 2 ) rephase_inc *= 2;
	else rephase_inc = UINT64_MAX;
	if ( conflicts <= UINT64_MAX - rephase_inc ) {
		rephase_limit = conflicts + rephase_inc;
	} else {
		rephase_limit = UINT64_MAX;
	}
	rephases ++;
}

// Clause deletion
void Solver::reduce() {
        // Preserve the current trail and every clause used as its reason.
        reduces = 0;
        if ( reduce_limit <= UINT64_MAX - 512 ) reduce_limit += 512;
        else reduce_limit = UINT64_MAX;
        ++reductionRuns;

        const int oldSize = static_cast<int>(clauseDB.size());
        reduceMap.assign(oldSize, -1);

        std::vector<unsigned char> locked(oldSize, 0);
        for ( int literal : trail ) {
                const int clause = reason[abs(literal)];
                if ( clause >= origin_clauses && clause < oldSize ) locked[clause] = 1;
        }

	std::vector<ClauseRank> candidates;
	candidates.reserve(oldSize - origin_clauses);
	for ( int i = origin_clauses; i < oldSize; i ++ ) {
		const Clause &clause = clauseDB[i];
		candidates.push_back({i, clause.lbd, clause.literals.size(), clause.activity});
	}

	// Glucose 4.2.1 also protects the most active 10%, rounding upward.
	std::sort(candidates.begin(), candidates.end(), higherClauseActivity);
	const size_t activeCount = candidates.size() - candidates.size() * 90 / 100;
	for ( size_t i = 0; i < activeCount; i ++ ) {
		clauseDB[candidates[i].clauseIdx].canBeDeleted = false;
	}
	std::sort(candidates.begin(), candidates.end(), worseClauseLBD);

	std::vector<unsigned char> erase(oldSize, 0);
	size_t deleteLimit = candidates.size() / 2;
	uint64_t deleteCount = 0;
	for ( size_t i = 0; i < candidates.size(); i ++ ) {
		const int cref = candidates[i].clauseIdx;
		Clause &clause = clauseDB[cref];
		if ( i < deleteLimit && clause.literals.size() > 2 &&
		     clause.lbd > GLUE_LBD && !locked[cref] && clause.canBeDeleted ) {
			erase[cref] = 1;
			deleteCount ++;
		} else {
			// A protected clause survives this cycle without consuming a deletion slot.
			if ( !clause.canBeDeleted && deleteLimit < candidates.size() ) deleteLimit ++;
			clause.canBeDeleted = true;
		}
	}
	deletedClauses += deleteCount;

        int newSize = origin_clauses;
        for ( int i = 0; i < origin_clauses; i ++ ) reduceMap[i] = i;
        for ( int i = origin_clauses; i < oldSize; i ++ ) {
                if ( erase[i] ) continue;
                if ( newSize != i ) clauseDB[newSize] = std::move(clauseDB[i]);
                reduceMap[i] = newSize ++;
        }
        clauseDB.erase(clauseDB.begin() + newSize, clauseDB.end());

        for ( int literal : trail ) {
                const int variable = abs(literal);
                if ( reason[variable] >= origin_clauses ) {
                        reason[variable] = reduceMap[reason[variable]];
                }
        }

        for ( int literal = -vars; literal <= vars; literal ++ ) {
                if ( literal == 0 ) continue;
                std::vector<WL> &watchers = WatchedLiterals(literal);
                int out = 0;
                for ( int i = 0; i < static_cast<int>(watchers.size()); i ++ ) {
                        const int oldIndex = watchers[i].clauseIdx;
                        const int newIndex = oldIndex < origin_clauses
                                ? oldIndex : reduceMap[oldIndex];
                        if ( newIndex == -1 ) continue;
                        watchers[i].clauseIdx = newIndex;
                        if ( out != i ) watchers[out] = watchers[i];
                        ++out;
                }
                watchers.resize(out);
        }
}

// Solver
int Solver::solve() {
        int result = 0;
        const double processStart = timeCheckerCPU();
        double timeLimit = 2000.0;
        if ( const char *env = getenv("UATU_TIMEOUT_SEC") ) {
                const double parsed = atof(env);
                if ( parsed > 0.0 ) timeLimit = parsed;
        }

        unsigned long long loopCounter = 0;
        auto updateLocalBest = [&]() {
                if ( static_cast<int>(trail.size()) <= threshold ) return;
                threshold = static_cast<int>(trail.size());
                memcpy(local_best + 1, value + 1,
                       static_cast<size_t>(vars) * sizeof(*value));
        };

        while ( !result ) {
                if ( (loopCounter++ & 4095ULL) == 0 &&
                     timeCheckerCPU() - processStart >= timeLimit ) {
                        result = 30;
                        break;
                }

                const int conflictClause = propagate();
                if ( conflictClause != -1 ) {
                        updateLocalBest();
			if ( !decVarInTrail.empty() ) updateRestartBlocking();

                        int backtrackLevel = 0;
                        int lbd = 0;
                        result = analyze(conflictClause, backtrackLevel, lbd);
                        if ( result != 0 ) break;

                        backtrack(backtrackLevel);
                        if ( learnt.size() == 1 ) {
                                assign(learnt[0], 0, -1);
                        } else {
                                const int learnedClause = add_clause(learnt);
                                clauseDB[learnedClause].lbd = lbd;
                                assign(learnt[0], backtrackLevel, learnedClause);
                        }

                        ++conflicts;
			updateVSIDSDecay();
			var_inc *= 1.0 / var_decay;
			clause_inc *= 1.0 / clause_decay;
                        ++reduces;
                } else if ( reduces >= reduce_limit ) {
                        reduce();
                } else if ( conflicts > 0 && lbd_queue_size == 50 &&
                            0.8 * fast_lbd_sum / lbd_queue_size >
                                    slow_lbd_sum / conflicts ) {
                        restart();
                } else if ( conflicts >= rephase_limit ) {
                        rephase();
                } else {
                        result = decide();
                }
        }

        processTimeFinal = timeCheckerCPU() - processStart;
        printf( "Elapsed Time [Total] (CPU): %.4f\n", processTimeFinal );
#if UATU_PROFILE_BCP
        printf( "Elapsed Time [Propa] (wall): %.4f\n", propagaTimeFinal );
        printf( "Elapsed Time [MaxBCP] (wall): %.4f\n", maxBCPTime );
#endif
        printf( "----------------------------------------------------\n" );
        return result;
}

// Print model when the result is SAT
void Solver::printModel() {
    	for ( int i = 1; i <= vars; i ++ ) printf( "%d ", value[i] * i );
    	printf( "0\n" );
}
