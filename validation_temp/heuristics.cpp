#include "solver.h"
#include <algorithm>
#include <inttypes.h>
#include <errno.h>
#include <stdexcept>
#include <string.h>

#define EVSIDS_DECAY_INTERVAL UINT64_C(5000)
#define EVSIDS_MAX_DECAY 0.95
#define RESTART_BLOCKING_DELAY UINT64_C(10000)
#define RESTART_BLOCKING_FACTOR 1.4
#define VIVIFY_MAX_CLAUSES 32
#define VIVIFY_MAX_SCAN 512
#define VIVIFY_MAX_LENGTH 32
#define VIVIFY_MAX_LBD 6
#define VIVIFY_MAX_WORK UINT64_C(1000000)
#define VIVIFY_CLAUSE_WORK UINT64_C(100000)

// Configuration changes CPU policies; it does not select another BCP engine.
static bool readSwitch( const char *name, bool fallback ) {
	const char *text = getenv(name);
	if ( text == nullptr ) return fallback;
	if ( strcmp(text, "0") == 0 ) return false;
	if ( strcmp(text, "1") == 0 ) return true;
	throw std::invalid_argument(name);
}

void configureHeuristics( Solver &solver ) {
	HeuristicState &h = solver.heuristics;
	h.adaptiveEVSIDS = readSwitch("UATU_H_ADAPTIVE_EVSIDS", true);
	h.blockedRestart = readSwitch("UATU_H_BLOCKED_RESTART", true);
	h.lbdReduction = readSwitch("UATU_H_LBD_REDUCTION", true);
	h.recursiveMinimization = readSwitch("UATU_H_RECURSIVE_MIN", true);
	h.vivification = readSwitch("UATU_H_VIVIFICATION", true);
	h.rephase = readSwitch("UATU_H_REPHASE", true);
	const char *initial = getenv("UATU_REDUCE_INITIAL");
	if ( initial != nullptr ) {
		char *end = nullptr;
		errno = 0;
		const unsigned long long parsed = strtoull(initial, &end, 10);
		if ( initial[0] == '-' || errno || end == initial || *end || !parsed ) {
			throw std::invalid_argument("UATU_REDUCE_INITIAL");
		}
		solver.reduce_limit = parsed;
	}
}

// Observe the pre-backjump trail, as in Glucose's blocked-restart policy.
void observeConflictTrail( Solver &solver ) {
	HeuristicState &h = solver.heuristics;
	if ( !h.blockedRestart ) return;
	const int count = static_cast<int>(solver.trail.size());
	if ( h.trailQueueSize == 5000 ) h.trailSum -= h.trailQueue[h.trailQueuePos];
	else h.trailQueueSize ++;
	h.trailQueue[h.trailQueuePos] = count;
	h.trailSum += static_cast<uint64_t>(count);
	h.trailQueuePos = (h.trailQueuePos + 1) % 5000;
	const double average = static_cast<double>(h.trailSum) / h.trailQueueSize;
	if ( solver.conflicts + 1 > RESTART_BLOCKING_DELAY &&
	     solver.lbd_queue_size == 50 && count > RESTART_BLOCKING_FACTOR * average ) {
		solver.fast_lbd_sum = 0.0;
		solver.lbd_queue_size = solver.lbd_queue_pos = 0;
		h.blockedRestarts ++;
	}
}

void updateAdaptiveDecay( Solver &solver ) {
	if ( solver.heuristics.adaptiveEVSIDS &&
	     (solver.conflicts + 1) % EVSIDS_DECAY_INTERVAL == 0 &&
	     solver.var_decay < EVSIDS_MAX_DECAY ) {
		solver.var_decay = std::min(EVSIDS_MAX_DECAY, solver.var_decay + 0.01);
		solver.heuristics.decayUpdates ++;
	}
}

// Iterative reason closure with successful-result reuse and failed-path rollback.
static bool redundantLiteral( Solver &solver, int variable, uint64_t levels ) {
	HeuristicState &h = solver.heuristics;
	const size_t checkpoint = h.minTouched.size();
	h.minStack.clear();
	h.minStack.push_back(variable);
	while ( !h.minStack.empty() ) {
		const int current = h.minStack.back();
		h.minStack.pop_back();
		const int cref = solver.reason[current];
		if ( cref < 0 || cref >= static_cast<int>(solver.clauseDB.size()) ) {
			throw std::logic_error("recursive minimization: invalid reason");
		}
		const Clause &clause = solver.clauseDB[cref];
		for ( int literal : clause.literals ) {
			const int next = abs(literal);
			if ( next == current || solver.level[next] == 0 || h.minKnown[next] ) continue;
			h.recursiveVisits ++;
			const int nextReason = solver.reason[next];
			if ( nextReason >= 0 && nextReason < static_cast<int>(solver.clauseDB.size()) &&
			     (levels & (UINT64_C(1) << (solver.level[next] & 63))) ) {
				h.minKnown[next] = 1;
				h.minTouched.push_back(next);
				h.minStack.push_back(next);
			} else {
				for ( size_t i = checkpoint; i < h.minTouched.size(); i ++ ) {
					h.minKnown[h.minTouched[i]] = 0;
				}
				h.minTouched.resize(checkpoint);
				return false;
			}
		}
	}
	return true;
}

void minimizeLearnedClauseRecursive( Solver &solver ) {
	HeuristicState &h = solver.heuristics;
	h.recursiveCalls ++;
	if ( solver.learnt.size() <= 1 ) return;
	if ( h.minKnown.empty() ) h.minKnown.assign(static_cast<size_t>(solver.vars) + 1, 0);
	h.minTouched.clear();
	uint64_t levels = 0;
	for ( int literal : solver.learnt ) {
		const int variable = abs(literal);
		h.minKnown[variable] = 1;
		h.minTouched.push_back(variable);
		levels |= UINT64_C(1) << (solver.level[variable] & 63);
	}
	int out = 1;
	for ( int i = 1; i < static_cast<int>(solver.learnt.size()); i ++ ) {
		const int literal = solver.learnt[i];
		const int variable = abs(literal);
		const int cref = solver.reason[variable];
		if ( cref >= 0 && redundantLiteral(solver, variable, levels) ) solver.minimizedLiterals ++;
		else solver.learnt[out ++] = literal;
	}
	solver.learnt.resize(out);
	for ( int variable : h.minTouched ) h.minKnown[variable] = 0;
	h.minTouched.clear();
	h.minStack.clear();
}

static void removeWatch( std::vector<WL> &watchers, int cref ) {
	int out = 0;
	int removed = 0;
	for ( int i = 0; i < static_cast<int>(watchers.size()); i ++ ) {
		if ( watchers[i].clauseIdx == cref ) removed ++;
		else watchers[out ++] = watchers[i];
	}
	watchers.resize(out);
	if ( removed != 1 ) throw std::logic_error("vivification: invalid watcher multiplicity");
}

// Temporary assumptions must not overwrite phase saving or search metadata.
static void undoProbe( Solver &solver, int rootSize ) {
	for ( int i = static_cast<int>(solver.trail.size()) - 1; i >= rootSize; i -- ) {
		const int variable = abs(solver.trail[i]);
		solver.value[variable] = 0;
		solver.reason[variable] = -1;
		solver.level[variable] = 0;
		if ( !solver.vsids.inHeap(variable) ) solver.vsids.insert(variable);
	}
	solver.trail.resize(rootSize);
	solver.decVarInTrail.clear();
	solver.propagated = rootSize;
	solver.heuristics.probing = false;
}

static bool rootLocked( const Solver &solver, int cref ) {
	for ( int literal : solver.clauseDB[cref].literals ) {
		const int variable = abs(literal);
		if ( solver.value[variable] && solver.reason[variable] == cref ) return true;
	}
	return false;
}

// Returns false only when root-level inconsistency has been established.
bool vivifyLearnedClauses( Solver &solver ) {
	HeuristicState &h = solver.heuristics;
	if ( !h.vivification ) return true;
	if ( !solver.decVarInTrail.empty() ) {
		throw std::logic_error("vivification: non-root entry");
	}
	if ( solver.propagate() != -1 ) return false;
	const uint64_t searchWork = h.propagationWork - h.previousWork;
	const uint64_t budget = std::min(searchWork / 50, VIVIFY_MAX_WORK);
	h.previousWork = h.propagationWork;
	if ( budget < 256 || static_cast<int>(solver.clauseDB.size()) <= solver.origin_clauses ) return true;
	const uint64_t endWork = h.propagationWork > UINT64_MAX - budget
		? UINT64_MAX : h.propagationWork + budget;
	h.vivificationRuns ++;
	int attempted = 0;
	const int total = static_cast<int>(solver.clauseDB.size());
	const int scan = std::min(VIVIFY_MAX_SCAN, total - solver.origin_clauses);
	for ( int scanned = 0; scanned < scan && attempted < VIVIFY_MAX_CLAUSES &&
	      h.propagationWork < endWork; scanned ++ ) {
		if ( h.vivifyCursor < solver.origin_clauses || h.vivifyCursor >= total ) {
			h.vivifyCursor = solver.origin_clauses;
		}
		const int cref = h.vivifyCursor ++;
		Clause &clause = solver.clauseDB[cref];
		if ( clause.literals.size() <= 2 || clause.literals.size() > VIVIFY_MAX_LENGTH ||
		     clause.lbd > VIVIFY_MAX_LBD || clause.useCount == 0 || rootLocked(solver, cref) ) continue;
		bool rootSatisfied = false;
		for ( int literal : clause.literals ) {
			if ( (literal > 0 ? solver.value[literal] : -solver.value[-literal]) == 1 ) {
				rootSatisfied = true;
				break;
			}
		}
		if ( rootSatisfied ) continue;

		const std::vector<int> original = clause.literals;
		std::vector<int> prefix;
		prefix.reserve(original.size());
		removeWatch(solver.watched_literals[solver.vars - original[0]], cref);
		removeWatch(solver.watched_literals[solver.vars - original[1]], cref);
		const int rootSize = static_cast<int>(solver.trail.size());
		h.probing = true;
		const uint64_t perClause = std::min(VIVIFY_CLAUSE_WORK, endWork - h.propagationWork);
		h.probeEnd = h.propagationWork + perClause;
		bool aborted = false;
		h.vivificationAttempts ++;
		attempted ++;
		for ( int literal : original ) {
			const int assigned = literal > 0 ? solver.value[literal] : -solver.value[-literal];
			if ( assigned == -1 ) continue;
			prefix.push_back(literal);
			if ( assigned == 1 ) break;
			solver.decVarInTrail.push_back(static_cast<int>(solver.trail.size()));
			solver.assign(-literal, static_cast<int>(solver.decVarInTrail.size()), -1);
			const int conflict = solver.propagate();
			if ( conflict == -2 ) { aborted = true; break; }
			if ( conflict >= 0 ) break;
		}
		undoProbe(solver, rootSize);
		if ( aborted ) h.vivificationAborts ++;
		if ( !aborted && prefix.size() < original.size() ) {
			if ( prefix.empty() ) { h.previousWork = h.propagationWork; return false; }
			clause.literals.swap(prefix);
			clause.lbd = std::min(clause.lbd, static_cast<int>(clause.literals.size()));
			clause.protectOnce = true;
			h.vivifiedClauses ++;
			h.vivifiedLiterals += original.size() - clause.literals.size();
		}
		if ( clause.literals.size() == 1 ) {
			const int literal = clause[0];
			const int assigned = literal > 0 ? solver.value[literal] : -solver.value[-literal];
			if ( assigned == -1 ) { h.previousWork = h.propagationWork; return false; }
			if ( assigned == 0 ) solver.assign(literal, 0, cref);
			h.vivificationUnits ++;
			if ( solver.propagate() != -1 ) { h.previousWork = h.propagationWork; return false; }
		} else {
			solver.watched_literals[solver.vars - clause[0]].push_back(WL(cref, clause[1]));
			solver.watched_literals[solver.vars - clause[1]].push_back(WL(cref, clause[0]));
		}
	}
	h.previousWork = h.propagationWork;
	return true;
}

void printHeuristicStatistics( const Solver &solver ) {
	const HeuristicState &h = solver.heuristics;
	printf( "Adaptive EVSIDS      : %d\n", h.adaptiveEVSIDS );
	printf( "Blocked LBD Restart  : %d\n", h.blockedRestart );
	printf( "LBD-First Reduction  : %d\n", h.lbdReduction );
	printf( "Recursive Minimize   : %d\n", h.recursiveMinimization );
	printf( "Selective Vivify     : %d\n", h.vivification );
	printf( "Current VSIDS Decay  : %.4f\n", solver.var_decay );
	printf( "Decay Updates        : %" PRIu64 "\n", h.decayUpdates );
	printf( "Blocked Restarts     : %" PRIu64 "\n", h.blockedRestarts );
	printf( "Protected Clauses    : %" PRIu64 "\n", h.protectedClauses );
	printf( "Recursive Calls      : %" PRIu64 "\n", h.recursiveCalls );
	printf( "Recursive Visits     : %" PRIu64 "\n", h.recursiveVisits );
	printf( "Vivification Runs    : %" PRIu64 "\n", h.vivificationRuns );
	printf( "Vivification Attempts: %" PRIu64 "\n", h.vivificationAttempts );
	printf( "Vivified Clauses     : %" PRIu64 "\n", h.vivifiedClauses );
	printf( "Vivified Literals    : %" PRIu64 "\n", h.vivifiedLiterals );
	printf( "Vivification Units   : %" PRIu64 "\n", h.vivificationUnits );
	printf( "Vivification Aborts  : %" PRIu64 "\n", h.vivificationAborts );
}
