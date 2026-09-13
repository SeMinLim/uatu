#include "solver.h"
#include <algorithm>
#include <chrono>
#include <deque>
#include <utility>


// Glucose 4.2.1 simp defaults; no additional occurrence or work cutoffs.
static constexpr size_t PREPROCESS_CLAUSE_LIMIT = 4800000;
static constexpr size_t PREPROCESS_RESOLVENT_LIMIT = 20;
static constexpr size_t PREPROCESS_SUBSUMPTION_LIMIT = 1000;

struct PreprocessState {
	Solver *solver;
	std::vector<std::vector<int> > occurs;
	std::vector<uint64_t> literalCount;
	std::vector<uint32_t> abstraction;
	std::vector<uint8_t> touched;
	std::vector<uint8_t> queued;
	std::vector<int> heap;
	std::vector<int> position;
	std::deque<int> subsumptionQueue;
	size_t rootCursor = 0;
	size_t touchedCount = 0;
	uint64_t storedLiterals = 0;
	uint64_t deletedLiterals = 0;
	uint64_t budgetChecks = 0;
};

static bool preprocessingExpired( PreprocessState &state ) {
	state.budgetChecks ++;
	if ( (state.budgetChecks & 1023) != 0 ) return false;
	return !state.solver->withinBudget();
}

static uint32_t preprocessAbstraction( const Clause &clause ) {
	uint32_t result = 0;
	for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
		result |= uint32_t(1) << (abs(clause.literals[i]) & 31);
	}
	return result;
}

static uint64_t eliminationCost( const PreprocessState &state, int variable ) {
	const int vars = state.solver->vars;
	return state.literalCount[vars + variable] * state.literalCount[vars - variable];
}

static int moveEliminationUp( PreprocessState &state, int position ) {
	const int variable = state.heap[position];
	while ( position > 0 ) {
		const int parent = (position - 1) / 2;
		if ( eliminationCost(state, variable) >= eliminationCost(state, state.heap[parent]) ) break;
		state.heap[position] = state.heap[parent];
		state.position[state.heap[position]] = position;
		position = parent;
	}
	state.heap[position] = variable;
	state.position[variable] = position;
	return position;
}

static void moveEliminationDown( PreprocessState &state, int position ) {
	const int variable = state.heap[position];
	while ( static_cast<size_t>(position) < state.heap.size() / 2 ) {
		int child = position * 2 + 1;
		if ( static_cast<size_t>(child + 1) < state.heap.size() &&
		     eliminationCost(state, state.heap[child + 1]) < eliminationCost(state, state.heap[child]) ) child ++;
		if ( eliminationCost(state, variable) <= eliminationCost(state, state.heap[child]) ) break;
		state.heap[position] = state.heap[child];
		state.position[state.heap[position]] = position;
		position = child;
	}
	state.heap[position] = variable;
	state.position[variable] = position;
}

static void updateEliminationHeap( PreprocessState &state, int variable, bool allowInsert ) {
	Solver &solver = *state.solver;
	int position = state.position[variable];
	if ( position < 0 ) {
		if ( !allowInsert || solver.eliminated[variable] || solver.value[variable] != 0 ) return;
		position = static_cast<int>(state.heap.size());
		state.heap.push_back(variable);
		state.position[variable] = position;
	}
	position = moveEliminationUp(state, position);
	moveEliminationDown(state, position);
}

static int popEliminationHeap( PreprocessState &state ) {
	const int variable = state.heap[0];
	state.position[variable] = -1;
	if ( state.heap.size() == 1 ) {
		state.heap.pop_back();
		return variable;
	}
	state.heap[0] = state.heap.back();
	state.heap.pop_back();
	state.position[state.heap[0]] = 0;
	moveEliminationDown(state, 0);
	return variable;
}

static void queuePreprocessClause( PreprocessState &state, int clauseIdx ) {
	if ( state.queued[clauseIdx] || state.solver->clauseDB[clauseIdx].removed ) return;
	state.queued[clauseIdx] = 1;
	state.subsumptionQueue.push_back(clauseIdx);
}

static void cleanPreprocessOccurrences( PreprocessState &state, int variable ) {
	std::vector<int> &occurs = state.occurs[variable];
	size_t output = 0;
	for ( size_t i = 0; i < occurs.size(); i ++ ) {
		if ( !state.solver->clauseDB[occurs[i]].removed ) occurs[output ++] = occurs[i];
	}
	occurs.resize(output);
}

static void detachPreprocessClause( Solver &solver, int clauseIdx ) {
	const Clause &clause = solver.clauseDB[clauseIdx];
	if ( clause.literals.size() < 2 ) return;
	for ( int watched = 0; watched < 2; watched ++ ) {
		std::vector<WL> &list = solver.watched_literals[solver.vars - clause.literals[watched]];
		size_t output = 0;
		for ( size_t i = 0; i < list.size(); i ++ ) {
			if ( list[i].clauseIdx != clauseIdx ) list[output ++] = list[i];
		}
		list.resize(output);
	}
}

static void attachPreprocessClause( Solver &solver, int clauseIdx ) {
	const Clause &clause = solver.clauseDB[clauseIdx];
	solver.watched_literals[solver.vars - clause.literals[0]].push_back(WL(clauseIdx, clause.literals[1]));
	solver.watched_literals[solver.vars - clause.literals[1]].push_back(WL(clauseIdx, clause.literals[0]));
}

static void indexPreprocessClause( PreprocessState &state, int clauseIdx, bool touch ) {
	const Clause &clause = state.solver->clauseDB[clauseIdx];
	const int vars = state.solver->vars;
	state.abstraction[clauseIdx] = preprocessAbstraction(clause);
	for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
		const int literal = clause.literals[i];
		const int variable = abs(literal);
		state.occurs[variable].push_back(clauseIdx);
		state.literalCount[vars + literal] ++;
		if ( touch && !state.touched[variable] ) {
			state.touched[variable] = 1;
			state.touchedCount ++;
		}
		updateEliminationHeap(state, variable, false);
	}
	state.storedLiterals += clause.literals.size();
}

static void removePreprocessClause( PreprocessState &state, int clauseIdx ) {
	Solver &solver = *state.solver;
	Clause &clause = solver.clauseDB[clauseIdx];
	if ( clause.removed ) return;
	detachPreprocessClause(solver, clauseIdx);
	clause.removed = true;
	state.deletedLiterals += clause.literals.size();
	for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
		const int literal = clause.literals[i];
		const int variable = abs(literal);
		state.literalCount[solver.vars + literal] --;
		updateEliminationHeap(state, variable, true);
		if ( solver.reason[variable] == clauseIdx ) solver.reason[variable] = -1;
	}
}

static int propagatePreprocessUnit( Solver &solver, int literal ) {
	const int assigned = literal > 0 ? solver.value[literal] : -solver.value[-literal];
	if ( assigned == -1 ) return 20;
	if ( assigned == 0 ) solver.assign(literal, 0, -1);
	return solver.propagate() == -1 ? 0 : 20;
}

static int strengthenPreprocessClause( PreprocessState &state, int clauseIdx, int literal ) {
	Solver &solver = *state.solver;
	Clause &clause = solver.clauseDB[clauseIdx];
	queuePreprocessClause(state, clauseIdx);
	if ( clause.literals.size() == 2 ) {
		const int unit = clause.literals[0] == literal ? clause.literals[1] : clause.literals[0];
		removePreprocessClause(state, clauseIdx);
		return propagatePreprocessUnit(solver, unit);
	}
	detachPreprocessClause(solver, clauseIdx);
	clause.literals.erase(std::find(clause.literals.begin(), clause.literals.end(), literal));
	state.abstraction[clauseIdx] = preprocessAbstraction(clause);
	state.deletedLiterals ++;
	std::vector<int> &occurs = state.occurs[abs(literal)];
	occurs.erase(std::remove(occurs.begin(), occurs.end(), clauseIdx), occurs.end());
	state.literalCount[solver.vars + literal] --;
	updateEliminationHeap(state, abs(literal), true);
	attachPreprocessClause(solver, clauseIdx);
	return 0;
}

// Return 0 for no relation, 1 for subsumption, 2 for self-subsuming resolution.
static int preprocessSubsumes( const std::vector<int> &small,
	const std::vector<int> &large, int &removeLiteral ) {
	if ( small.size() > large.size() ) return 0;
	removeLiteral = 0;
	for ( size_t i = 0; i < small.size(); i ++ ) {
		bool found = false;
		for ( size_t j = 0; j < large.size(); j ++ ) {
			if ( large[j] == small[i] ) {
				found = true;
				break;
			}
			if ( large[j] == -small[i] ) {
				if ( removeLiteral != 0 ) return 0;
				removeLiteral = large[j];
				found = true;
				break;
			}
		}
		if ( !found ) return 0;
	}
	return removeLiteral == 0 ? 1 : 2;
}

static void gatherTouchedPreprocessClauses( PreprocessState &state ) {
	if ( state.touchedCount == 0 ) return;
	for ( int variable = 1; variable <= state.solver->vars; variable ++ ) {
		if ( !state.touched[variable] ) continue;
		cleanPreprocessOccurrences(state, variable);
		const std::vector<int> &occurs = state.occurs[variable];
		for ( size_t i = 0; i < occurs.size(); i ++ ) queuePreprocessClause(state, occurs[i]);
		state.touched[variable] = 0;
	}
	state.touchedCount = 0;
}

static int backwardPreprocessSubsumption( PreprocessState &state ) {
	Solver &solver = *state.solver;
	std::vector<int> unit(1);
	while ( !state.subsumptionQueue.empty() || state.rootCursor < solver.trail.size() ) {
		if ( preprocessingExpired(state) ) return 30;
		int source = -1;
		if ( !state.subsumptionQueue.empty() ) {
			source = state.subsumptionQueue.front();
			state.subsumptionQueue.pop_front();
			state.queued[source] = 0;
			if ( solver.clauseDB[source].removed ) continue;
		} else {
			unit[0] = solver.trail[state.rootCursor ++];
		}
		const std::vector<int> &small = source == -1 ? unit : solver.clauseDB[source].literals;
		const uint32_t signature = source == -1 ? uint32_t(1) << (abs(unit[0]) & 31) : state.abstraction[source];
		int best = abs(small[0]);
		for ( size_t i = 1; i < small.size(); i ++ ) {
			const int variable = abs(small[i]);
			if ( state.occurs[variable].size() < state.occurs[best].size() ) best = variable;
		}
		cleanPreprocessOccurrences(state, best);
		// Strengthening can erase an entry from the scanned list.
		size_t cursor = 0;
		while ( cursor < state.occurs[best].size() ) {
			if ( preprocessingExpired(state) ) return 30;
			if ( source != -1 && solver.clauseDB[source].removed ) break;
			const int target = state.occurs[best][cursor];
			const Clause &candidate = solver.clauseDB[target];
			if ( target == source || candidate.removed ||
			     candidate.literals.size() >= PREPROCESS_SUBSUMPTION_LIMIT ||
			     (signature & ~state.abstraction[target]) != 0 ) {
				cursor ++;
				continue;
			}
			int removeLiteral = 0;
			const int relation = preprocessSubsumes(small, candidate.literals, removeLiteral);
			if ( relation == 1 ) {
				removePreprocessClause(state, target);
				solver.preprocessingSubsumed ++;
			} else if ( relation == 2 ) {
				const bool erasesOccurrence = candidate.literals.size() > 2 && abs(removeLiteral) == best;
				const int result = strengthenPreprocessClause(state, target, removeLiteral);
				solver.preprocessingStrengthened ++;
				if ( result != 0 ) return result;
				if ( erasesOccurrence ) continue;
			}
			cursor ++;
		}
	}
	return 0;
}

// Keep the original merge order: the shorter clause contributes new literals first.
static bool makePreprocessResolvent( const Clause &positive, const Clause &negative,
	int variable, std::vector<int> &resolvent ) {
	const bool positiveShorter = positive.literals.size() < negative.literals.size();
	const std::vector<int> &longer = positiveShorter ? negative.literals : positive.literals;
	const std::vector<int> &shorter = positiveShorter ? positive.literals : negative.literals;
	resolvent.clear();
	for ( size_t i = 0; i < shorter.size(); i ++ ) {
		const int literal = shorter[i];
		if ( abs(literal) == variable ) continue;
		bool duplicate = false;
		for ( size_t j = 0; j < longer.size(); j ++ ) {
			if ( longer[j] == -literal ) return false;
			if ( longer[j] == literal ) {
				duplicate = true;
				break;
			}
		}
		if ( !duplicate ) resolvent.push_back(literal);
	}
	for ( size_t i = 0; i < longer.size(); i ++ ) {
		if ( abs(longer[i]) != variable ) resolvent.push_back(longer[i]);
	}
	return true;
}

static bool preprocessLiteralLess( int left, int right ) {
	if ( abs(left) != abs(right) ) return abs(left) < abs(right);
	return left > right;
}

static int addPreprocessResolvent( PreprocessState &state, std::vector<int> &resolvent ) {
	Solver &solver = *state.solver;
	size_t output = 0;
	for ( size_t i = 0; i < resolvent.size(); i ++ ) {
		const int literal = resolvent[i];
		const int assigned = literal > 0 ? solver.value[literal] : -solver.value[-literal];
		if ( assigned == 1 ) return 0;
		if ( assigned == 0 ) resolvent[output ++] = literal;
	}
	resolvent.resize(output);
	if ( output == 0 ) return 20;
	if ( output == 1 ) return propagatePreprocessUnit(solver, resolvent[0]);
	if ( solver.clauseDB.size() >= static_cast<size_t>(INT_MAX) ) return 30;
	std::sort(resolvent.begin(), resolvent.end(), preprocessLiteralLess);
	const int clauseIdx = solver.add_clause(resolvent);
	state.abstraction.push_back(0);
	state.queued.push_back(0);
	indexPreprocessClause(state, clauseIdx, true);
	queuePreprocessClause(state, clauseIdx);
	solver.preprocessingResolvents ++;
	return 0;
}

static int eliminatePreprocessVariable( PreprocessState &state, int variable ) {
	Solver &solver = *state.solver;
	cleanPreprocessOccurrences(state, variable);
	std::vector<int> positive, negative;
	const std::vector<int> occurrences = state.occurs[variable];
	for ( size_t i = 0; i < occurrences.size(); i ++ ) {
		const std::vector<int> &literals = solver.clauseDB[occurrences[i]].literals;
		if ( std::find(literals.begin(), literals.end(), variable) != literals.end() ) positive.push_back(occurrences[i]);
		else negative.push_back(occurrences[i]);
	}
	std::vector<int> resolvent;
	size_t generated = 0;
	for ( size_t p = 0; p < positive.size(); p ++ ) {
		for ( size_t n = 0; n < negative.size(); n ++ ) {
			if ( preprocessingExpired(state) ) return 30;
			if ( !makePreprocessResolvent(solver.clauseDB[positive[p]], solver.clauseDB[negative[n]], variable, resolvent) ) continue;
			generated ++;
			if ( generated > occurrences.size() || resolvent.size() > PREPROCESS_RESOLVENT_LIMIT ) return 0;
		}
	}

	// Save the smaller polarity side, followed by the opposite default assignment.
	const bool savePositive = positive.size() <= negative.size();
	const std::vector<int> &savedClauses = savePositive ? positive : negative;
	EliminationRecord record;
	record.variable = variable;
	record.defaultValue = savePositive ? -1 : 1;
	record.offset = solver.eliminationLiterals.size();
	for ( size_t i = 0; i < savedClauses.size(); i ++ ) {
		const std::vector<int> &literals = solver.clauseDB[savedClauses[i]].literals;
		for ( size_t j = 0; j < literals.size(); j ++ ) {
			if ( abs(literals[j]) != variable ) solver.eliminationLiterals.push_back(literals[j]);
		}
		solver.eliminationLiterals.push_back(0);
	}
	record.end = solver.eliminationLiterals.size();
	solver.eliminationRecords.push_back(record);
	solver.eliminated[variable] = 1;
	solver.preprocessingEliminated ++;

	for ( size_t p = 0; p < positive.size(); p ++ ) {
		for ( size_t n = 0; n < negative.size(); n ++ ) {
			if ( preprocessingExpired(state) ) return 30;
			if ( !makePreprocessResolvent(solver.clauseDB[positive[p]], solver.clauseDB[negative[n]], variable, resolvent) ) continue;
			const int result = addPreprocessResolvent(state, resolvent);
			if ( result != 0 ) return result;
		}
	}
	for ( size_t i = 0; i < occurrences.size(); i ++ ) removePreprocessClause(state, occurrences[i]);
	std::vector<int>().swap(state.occurs[variable]);
	return backwardPreprocessSubsumption(state);
}

static void collectPreprocessGarbage( PreprocessState &state ) {
	Solver &solver = *state.solver;
	if ( state.deletedLiterals <= state.storedLiterals / 2 ) return;
	std::vector<int> mapping(solver.clauseDB.size(), -1);
	int output = 0;
	for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
		if ( !solver.clauseDB[i].removed ) mapping[i] = output ++;
	}
	std::deque<int> pending;
	for ( size_t i = 0; i < state.subsumptionQueue.size(); i ++ ) {
		const int mapped = mapping[state.subsumptionQueue[i]];
		if ( mapped != -1 ) pending.push_back(mapped);
	}
	solver.compactClauses();
	state.subsumptionQueue.swap(pending);
	state.queued.assign(solver.clauseDB.size(), 0);
	for ( size_t i = 0; i < state.subsumptionQueue.size(); i ++ ) state.queued[state.subsumptionQueue[i]] = 1;
	state.abstraction.assign(solver.clauseDB.size(), 0);
	for ( int variable = 1; variable <= solver.vars; variable ++ ) state.occurs[variable].clear();
	std::fill(state.literalCount.begin(), state.literalCount.end(), 0);
	state.deletedLiterals = state.storedLiterals = 0;
	// Rebuild occurrence data without temporarily changing the elimination heap.
	for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
		const Clause &clause = solver.clauseDB[i];
		state.abstraction[i] = preprocessAbstraction(clause);
		state.storedLiterals += clause.literals.size();
		for ( size_t j = 0; j < clause.literals.size(); j ++ ) {
			const int literal = clause.literals[j];
			state.occurs[abs(literal)].push_back(static_cast<int>(i));
			state.literalCount[solver.vars + literal] ++;
		}
	}
}

int Solver::preprocess() {
	const std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
	eliminated.assign(static_cast<size_t>(vars) + 1, 0);
	eliminationRecords.clear();
	eliminationLiterals.clear();
	int result = simplifyRoot() ? 0 : 20;
	if ( result == 0 && clauseDB.size() <= PREPROCESS_CLAUSE_LIMIT ) {
		PreprocessState state;
		state.solver = this;
		state.occurs.resize(static_cast<size_t>(vars) + 1);
		state.literalCount.assign(static_cast<size_t>(vars) * 2 + 1, 0);
		state.abstraction.assign(clauseDB.size(), 0);
		state.touched.assign(static_cast<size_t>(vars) + 1, 0);
		state.queued.assign(clauseDB.size(), 0);
		state.position.assign(static_cast<size_t>(vars) + 1, -1);
		for ( int variable = 1; variable <= vars; variable ++ ) updateEliminationHeap(state, variable, true);
		for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
			indexPreprocessClause(state, static_cast<int>(i), true);
			queuePreprocessClause(state, static_cast<int>(i));
		}
		while ( result == 0 && (state.touchedCount != 0 || state.rootCursor < trail.size() || !state.heap.empty()) ) {
			gatherTouchedPreprocessClauses(state);
			result = backwardPreprocessSubsumption(state);
			while ( result == 0 && !state.heap.empty() ) {
				if ( preprocessingExpired(state) ) {
					result = 30;
					break;
				}
				const int variable = popEliminationHeap(state);
				if ( eliminated[variable] || value[variable] != 0 ) continue;
				result = eliminatePreprocessVariable(state, variable);
				collectPreprocessGarbage(state);
			}
		}
		compactClauses();
		propagated = 0;
		if ( result == 0 && !simplifyRoot() ) result = 20;
	}
	preprocessTimeFinal += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
	return result;
}

// Reconstruct in reverse elimination order, after each residual variable is known.
bool Solver::extendModel() {
	for ( int variable = 1; variable <= vars; variable ++ ) {
		if ( value[variable] == 0 ) value[variable] = -1;
	}
	for ( size_t i = eliminationRecords.size(); i > 0; i -- ) {
		const EliminationRecord &record = eliminationRecords[i - 1];
		int assigned = record.defaultValue;
		bool satisfied = false;
		for ( size_t j = record.offset; j < record.end; j ++ ) {
			const int literal = eliminationLiterals[j];
			if ( literal == 0 ) {
				if ( !satisfied ) assigned = -record.defaultValue;
				satisfied = false;
			} else if ( (literal > 0 ? value[literal] : -value[-literal]) == 1 ) {
				satisfied = true;
			}
		}
		value[record.variable] = static_cast<int8_t>(assigned);
	}
	return true;
}
