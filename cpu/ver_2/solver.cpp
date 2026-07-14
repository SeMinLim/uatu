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

// Functions for reading CNF (Conjunctive Normal Form) file
uint8_t *read_whitespace( uint8_t *p ) {
        // ASCII
	// 9 : Horizontal tab, 	10: Line feed or new line
	// 11: Vertical tab,	12: Form feed or new page
	// 13: Carriage return	32: Space
        while ( (*p >= 9 && *p <= 13) || *p == 32 ) ++p;
        
	return p;
}
uint8_t *read_until_new_line( uint8_t *p ) {
        while ( *p != '\n' ) {
                if ( *p++ == '\0' ) exit(1);
        }
        
	return ++p;
}
uint8_t *read_int( uint8_t *p, int *i ) {
        bool sym = true;
        *i = 0;
        
	p = read_whitespace(p);
        
	if ( *p == '-' ) {
                sym = false;
                ++ p;
        }
        
	while ( *p >= '0' && *p <= '9' ) {
                if ( *p == '\0' ) {
			return p;
		} else {
			*i = *i * 10 + *p - '0';
			++ p;
		}
        }
        
	if ( !sym ) *i = -(*i);
        
	return p;
}


//// Solver
// Allocate memory and initialize the values
void Solver::initialize( void ) {
        value = new int8_t[vars + 1];
        local_best = new int8_t[vars + 1];
        saved = new int8_t[vars + 1];
        reason = new int[vars + 1];
        level = new int[vars + 1];
        mark = new int[vars + 1];
        activity = new double[vars + 1];
        watched_literals = new std::vector<WL>[vars * 2 + 1];

        clauseDB.reserve(static_cast<size_t>(clauses) + static_cast<size_t>(clauses / 16));
        trail.reserve(vars);
        decVarInTrail.reserve(vars);
        learnt.reserve(64);

        conflicts = decides = unitPropagations = bcpFunctionCalls = 0;
        lbdResets = rephases = reduces = 0;
        reductionRuns = 0;
        deletedClauses = minimizedLiterals = 0;
        threshold = propagated = time_stamp = 0;
        fast_lbd_sum = lbd_queue_size = lbd_queue_pos = slow_lbd_sum = 0;
        processTimeFinal = propagaTimeFinal = maxBCPTime = 0.0;

        var_inc = 1;
        var_decay = 0.8;
        rephase_inc = 100000;
        rephase_limit = 100000;
        reduce_limit = 8192;

        vsids.initialize(activity);
        for (int i = 1; i <= vars; ++i) {
                value[i] = local_best[i] = saved[i] = 0;
                reason[i] = level[i] = mark[i] = 0;
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
    	value[var]  = literal > 0 ? 1 : -1;
    	level[var]  = l;
	reason[var] = cref;                                         
    	trail.push_back(literal);
}

// Add a clause to the database
int Solver::add_clause( std::vector<int> &c ) {                   
    	clauseDB.push_back(Clause(c.size()));                          
    	
	int id = clauseDB.size() - 1;                                
    	for ( int i = 0; i < (int)c.size(); i++ ) clauseDB[id][i] = c[i];
        
	// Two watched literals
	// We only make the literals 'true'
	// Then our only concern is the opposite ones, -c[0] and -c[1]
	// c[0] is a blocker for c[1] and vice versa
    	WatchedLiterals(-c[0]).push_back(WL(id, c[1])); // watched_literals[vars-c[0]]                      
    	WatchedLiterals(-c[1]).push_back(WL(id, c[0])); // watched_literals[vars-c[1]]

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
                if (seconds > maxBCPTime) maxBCPTime = seconds;
        };
#endif

        while (propagated < static_cast<int>(trail.size())) {
                const int p = trail[propagated++];
                std::vector<WL> &ws = WatchedLiterals(p);
                const int numClauses = static_cast<int>(ws.size());
                int out = 0;

                for (int i = 0; i < numClauses;) {
                        const int blocker = ws[i].blocker;
                        if (Value(blocker) == 1) {
                                ws[out++] = ws[i++];
                                continue;
                        }

                        const int cref = ws[i].clauseIdx;
                        Clause &c = clauseDB[cref];
                        const int falseLiteral = -p;
                        if (c[0] == falseLiteral) {
                                c[0] = c[1];
                                c[1] = falseLiteral;
                        }
                        ++i;

                        const int firstWatch = c[0];
                        const WL watcher(cref, firstWatch);
                        if (Value(firstWatch) == 1) {
                                ws[out++] = watcher;
                                continue;
                        }

                        int k = 2;
                        const int size = static_cast<int>(c.literals.size());
                        while (k < size && Value(c[k]) == -1) ++k;

                        if (k < size) {
                                c[1] = c[k];
                                c[k] = falseLiteral;
                                WatchedLiterals(-c[1]).push_back(watcher);
                        } else {
                                ws[out++] = watcher;
                                if (Value(firstWatch) == -1) {
                                        while (i < numClauses) ws[out++] = ws[i++];
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

// Read CNF file
int Solver::parse( char *filename ) {
        FILE *file = fopen(filename, "rb");
        if (!file) {
                fprintf(stderr, "failed to open '%s': %s\n", filename, strerror(errno));
                return 30;
        }
        if (fseek(file, 0, SEEK_END) != 0) {
                fclose(file);
                return 30;
        }
        const long end = ftell(file);
        if (end < 0) {
                fclose(file);
                return 30;
        }
        rewind(file);

        const size_t length = static_cast<size_t>(end);
        std::vector<uint8_t> data(length + 1);
        if (fread(data.data(), sizeof(uint8_t), length, file) != length) {
                fclose(file);
                return 30;
        }
        fclose(file);
        data[length] = '\0';
        uint8_t *cursor = data.data();

        std::vector<int> buffer;
        buffer.reserve(16);

        while (*cursor != '\0') {
                cursor = read_whitespace(cursor);
                if (*cursor == '\0') break;

                if (*cursor == 'c') {
                        cursor = read_until_new_line(cursor);
                } else if (*cursor == 'p') {
                        if (*(cursor + 1) == ' ' && *(cursor + 2) == 'c' &&
                            *(cursor + 3) == 'n' && *(cursor + 4) == 'f') {
                                cursor += 5;
                                cursor = read_int(cursor, &vars);
                                cursor = read_int(cursor, &clauses);
                                initialize();
                        } else {
                                fprintf(stderr, "PARSE ERROR: unexpected header\n");
                                return 30;
                        }
                } else {
                        int32_t literal = 0;
                        cursor = read_int(cursor, &literal);
                        if (literal != 0) {
                                if (*cursor == '\0') {
                                        fprintf(stderr, "PARSE ERROR: unexpected EOF\n");
                                        return 30;
                                }
                                buffer.push_back(literal);
                        } else {
                                if (buffer.empty()) return 20;
                                if (buffer.size() == 1) {
                                        if (Value(buffer[0]) == -1) return 20;
                                        if (Value(buffer[0]) == 0) assign(buffer[0], 0, -1);
                                } else {
                                        add_clause(buffer);
                                }
                                buffer.clear();
                        }
                }
        }

        origin_clauses = static_cast<int>(clauseDB.size());
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

// Update activity
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

// Conflict analysis
int Solver::analyze( int conflict, int &backtrackLevel, int &lbd ) {
        ++time_stamp;
        learnt.clear();

        // Preserve the original solver's conflict-level convention.
        const int conflictLevel = level[abs(clauseDB[conflict][0])];
        if (conflictLevel == 0) return 20;

        learnt.push_back(0);
        int unresolved = 0;
        int resolveLiteral = 0;
        int trailIndex = static_cast<int>(trail.size()) - 1;
        std::vector<int> bump;
        bump.reserve(32);

        do {
                Clause &clause = clauseDB[conflict];
                const int begin = resolveLiteral == 0 ? 0 : 1;
                for (int i = begin; i < static_cast<int>(clause.literals.size()); ++i) {
                        const int variable = abs(clause[i]);
                        if (mark[variable] == time_stamp || level[variable] == 0) continue;

                        update_score(variable, 0.5);
                        bump.push_back(variable);
                        mark[variable] = time_stamp;

                        if (level[variable] >= conflictLevel) ++unresolved;
                        else learnt.push_back(clause[i]);
                }

                while (trailIndex >= 0 &&
                       mark[abs(trail[trailIndex])] != time_stamp) --trailIndex;
                if (trailIndex < 0) {
                        fprintf(stderr, "internal error: malformed implication graph\n");
                        abort();
                }

                resolveLiteral = trail[trailIndex--];
                conflict = reason[abs(resolveLiteral)];
                mark[abs(resolveLiteral)] = 0;
                --unresolved;
        } while (unresolved > 0);

        learnt[0] = -resolveLiteral;

        // Non-recursive, one-step reason minimization.
        if (learnt.size() > 1) {
                ++time_stamp;
                const int membershipStamp = time_stamp;
                for (int literal : learnt) mark[abs(literal)] = membershipStamp;

                int out = 1;
                for (int i = 1; i < static_cast<int>(learnt.size()); ++i) {
                        const int literal = learnt[i];
                        const int variable = abs(literal);
                        const int reasonClause = reason[variable];
                        bool removable = reasonClause >= 0;

                        if (removable) {
                                const Clause &reasonData = clauseDB[reasonClause];
                                for (int q : reasonData.literals) {
                                        const int qvar = abs(q);
                                        if (qvar == variable || level[qvar] == 0) continue;
                                        if (mark[qvar] != membershipStamp) {
                                                removable = false;
                                                break;
                                        }
                                }
                        }

                        if (removable) ++minimizedLiterals;
                        else learnt[out++] = literal;
                }
                learnt.resize(out);
        }

        ++time_stamp;
        lbd = 0;
        for (int literal : learnt) {
                const int decisionLevel = level[abs(literal)];
                if (decisionLevel && mark[decisionLevel] != time_stamp) {
                        mark[decisionLevel] = time_stamp;
                        ++lbd;
                }
        }

        if (lbd_queue_size < 50) ++lbd_queue_size;
        else fast_lbd_sum -= lbd_queue[lbd_queue_pos];
        lbd_queue[lbd_queue_pos++] = lbd;
        if (lbd_queue_pos == 50) lbd_queue_pos = 0;
        fast_lbd_sum += lbd;
        slow_lbd_sum += lbd > 50 ? 50 : lbd;

        if (learnt.size() == 1) {
                backtrackLevel = 0;
        } else {
                int maxIndex = 1;
                for (int i = 2; i < static_cast<int>(learnt.size()); ++i)
                        if (level[abs(learnt[i])] > level[abs(learnt[maxIndex])])
                                maxIndex = i;
                std::swap(learnt[1], learnt[maxIndex]);
                backtrackLevel = level[abs(learnt[1])];
        }

        // Original second-stage bump retained after the ablation trial.
        for (int variable : bump)
                if (level[variable] >= backtrackLevel - 1)
                        update_score(variable, 1.0);

        return 0;
}

// Backtracking
void Solver::backtrack( int backtrackLevel ) {
    	if ( (int)decVarInTrail.size() <= backtrackLevel ) {
		return;
	} else {
		for ( int i = trail.size() - 1; i >= decVarInTrail[backtrackLevel]; i -- ) {
			// Delete assignment
			int v = abs(trail[i]);
			value[v] = 0;

			// Phase saving
			saved[v] = trail[i] > 0 ? 1 : -1;
			
			// Store variable back to VSIDS heap
			if ( !vsids.inHeap(v) ) vsids.insert(v);
		}

		// Parameter and array update
		propagated = decVarInTrail[backtrackLevel];
		trail.resize(propagated);
		decVarInTrail.resize(backtrackLevel);
	}
}

// Restart
void Solver::resetRecentLBD() {
        fast_lbd_sum = 0;
        lbd_queue_size = 0;
        lbd_queue_pos = 0;
        ++lbdResets;
}

// Rephase
void Solver::rephase() {
        // Exact original soft-rephase sequence: preserve the current trail.
        if (rephases / 2 == 1) {
                for (int i = 1; i <= vars; ++i) saved[i] = local_best[i];
        } else {
                for (int i = 1; i <= vars; ++i) saved[i] = -local_best[i];
        }

        rephase_inc *= 2;
        rephase_limit = conflicts + rephase_inc;
        ++rephases;
}

// Clause deletion
void Solver::reduce() {
        // The only heuristic that performs a root backtrack.
        backtrack(0);
        reduces = 0;
        reduce_limit += 512;
        ++reductionRuns;

        const int oldSize = static_cast<int>(clauseDB.size());
        reduceMap.assign(oldSize, -1);

        std::vector<unsigned char> locked(oldSize, 0);
        for (int literal : trail) {
                const int clause = reason[abs(literal)];
                if (clause >= origin_clauses && clause < oldSize) locked[clause] = 1;
        }

        std::vector<int> candidates;
        candidates.reserve(oldSize - origin_clauses);
        for (int i = origin_clauses; i < oldSize; ++i)
                if (!locked[i] && clauseDB[i].lbd >= 5)
                        candidates.push_back(i);

        std::sort(candidates.begin(), candidates.end(), [&](int a, int b) {
                if (clauseDB[a].lbd != clauseDB[b].lbd)
                        return clauseDB[a].lbd > clauseDB[b].lbd;
                if (clauseDB[a].literals.size() != clauseDB[b].literals.size())
                        return clauseDB[a].literals.size() > clauseDB[b].literals.size();
                return a < b;
        });

        std::vector<unsigned char> erase(oldSize, 0);
        const size_t deleteCount = candidates.size() / 2;
        for (size_t i = 0; i < deleteCount; ++i) erase[candidates[i]] = 1;
        deletedClauses += static_cast<long long>(deleteCount);

        int newSize = origin_clauses;
        for (int i = 0; i < origin_clauses; ++i) reduceMap[i] = i;
        for (int i = origin_clauses; i < oldSize; ++i) {
                if (erase[i]) continue;
                if (newSize != i) clauseDB[newSize] = std::move(clauseDB[i]);
                reduceMap[i] = newSize++;
        }
        clauseDB.erase(clauseDB.begin() + newSize, clauseDB.end());

        for (int literal : trail) {
                const int variable = abs(literal);
                if (reason[variable] >= origin_clauses)
                        reason[variable] = reduceMap[reason[variable]];
        }

        for (int literal = -vars; literal <= vars; ++literal) {
                if (literal == 0) continue;
                std::vector<WL> &watchers = WatchedLiterals(literal);
                int out = 0;
                for (int i = 0; i < static_cast<int>(watchers.size()); ++i) {
                        const int oldIndex = watchers[i].clauseIdx;
                        const int newIndex = oldIndex < origin_clauses
                                ? oldIndex : reduceMap[oldIndex];
                        if (newIndex == -1) continue;
                        watchers[i].clauseIdx = newIndex;
                        if (out != i) watchers[out] = watchers[i];
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
        if (const char *env = getenv("UATU_TIMEOUT_SEC")) {
                const double parsed = atof(env);
                if (parsed > 0.0) timeLimit = parsed;
        }

        unsigned long long loopCounter = 0;
        auto updateLocalBest = [&]() {
                if (static_cast<int>(trail.size()) <= threshold) return;
                threshold = static_cast<int>(trail.size());
                memcpy(local_best + 1, value + 1,
                       static_cast<size_t>(vars) * sizeof(*value));
        };

        while (!result) {
                if ((loopCounter++ & 4095ULL) == 0 &&
                    timeCheckerCPU() - processStart >= timeLimit) {
                        result = 30;
                        break;
                }

                const int conflictClause = propagate();
                if (conflictClause != -1) {
                        updateLocalBest();

                        int backtrackLevel = 0;
                        int lbd = 0;
                        result = analyze(conflictClause, backtrackLevel, lbd);
                        if (result == 20) break;

                        backtrack(backtrackLevel);
                        if (learnt.size() == 1) {
                                assign(learnt[0], 0, -1);
                        } else {
                                const int learnedClause = add_clause(learnt);
                                clauseDB[learnedClause].lbd = lbd;
                                assign(learnt[0], backtrackLevel, learnedClause);
                        }

                        var_inc *= 1.0 / var_decay;
                        ++conflicts;
                        ++reduces;
                } else if (reduces >= reduce_limit) {
                        reduce();
                } else if (lbd_queue_size == 50 &&
                           0.8 * fast_lbd_sum / lbd_queue_size >
                                   slow_lbd_sum / conflicts) {
                        resetRecentLBD();
                } else if (conflicts >= rephase_limit) {
                        rephase();
                } else {
                        result = decide();
                }
        }

        processTimeFinal = timeCheckerCPU() - processStart;
        printf("Elapsed Time [Total] (CPU): %.4f\n", processTimeFinal);
#if UATU_PROFILE_BCP
        printf("Elapsed Time [Propa] (wall): %.4f\n", propagaTimeFinal);
        printf("Elapsed Time [MaxBCP] (wall): %.4f\n", maxBCPTime);
#endif
        printf("----------------------------------------------------\n");
        return result;
}

// Print model when the result is SAT
void Solver::printModel() {
    	for ( int i = 1; i <= vars; i++ ) printf("%d ", value[i] * i);
    	printf( "0\n" );
}
