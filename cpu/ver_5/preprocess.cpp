#include "solver.h"
#include <algorithm>
#include <chrono>
#include <utility>


static constexpr uint64_t PREPROCESS_WORK_LIMIT = 40000000;
static constexpr uint64_t PREPROCESS_SUBSUMPTION_WORK = 8000000;
static constexpr uint64_t PREPROCESS_OCCURRENCE_BYTES = 128 * 1024 * 1024;
static constexpr size_t PREPROCESS_GENERATED_LITERALS = 2000000;
static constexpr size_t PREPROCESS_EXTENSION_LITERALS = 4000000;
static constexpr size_t PREPROCESS_MAX_OCCURRENCES = 64;
static constexpr size_t PREPROCESS_MAX_RESOLVENT_SIZE = 64;
static constexpr size_t PREPROCESS_SUBSUMING_SIZE = 32;
static constexpr size_t PREPROCESS_SUBSUMED_SIZE = 512;
static constexpr int PREPROCESS_ELIMINATION_ROUNDS = 2;


// Bounded resolution and reverse extension follow the standard MiniSAT simp
// algorithm: niklasso/minisat, eb01ad68, simp/SimpSolver.cc. Independent code.
struct PreprocessOccurrence {
	int clauseIdx;
	int next;
};

struct PreprocessState {
	Solver *solver;
	std::vector<int> head;
	std::vector<uint32_t> count;
	std::vector<PreprocessOccurrence> nodes;
	std::vector<uint8_t> deleted;
	size_t nodeLimit;
	size_t generatedLiterals;
};

static bool preprocessLiteralLess( int a, int b ) {
	if ( abs(a) != abs(b) ) return abs(a) < abs(b);
	return a < b;
}

static bool preprocessCharge( PreprocessState &state, uint64_t work ) {
	Solver &solver = *state.solver;
	if ( work > PREPROCESS_WORK_LIMIT - solver.preprocessingWork ) return false;
	solver.preprocessingWork += work;
	return true;
}

static int finishPreprocessing( Solver &solver,
	std::chrono::steady_clock::time_point start, int result ) {
	solver.preprocessTimeFinal +=
		std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
	return result;
}

// Clear obsolete indices only at root, then replay all permanent assignments.
static int rebuildPreprocessRoot( Solver &solver, bool normalize ) {
	while ( true ) {
		const size_t trailBefore = solver.trail.size();
		size_t output = 0;
		for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
			Clause &clause = solver.clauseDB[i];
			if ( clause.literals.empty() ) continue;
			bool satisfied = false;
			size_t remaining = 0;
			uint32_t positiveStamp = 0, negativeStamp = 0;
			if ( normalize ) {
				solver.nextAnalysisStamp();
				positiveStamp = solver.time_stamp;
				solver.nextAnalysisStamp();
				negativeStamp = solver.time_stamp;
			}
			for ( size_t j = 0; j < clause.literals.size(); j ++ ) {
				const int literal = clause.literals[j];
				const int variable = abs(literal);
				const int assigned = literal > 0 ? solver.value[variable] : -solver.value[variable];
				if ( assigned == 1 ) {
					satisfied = true;
					break;
				}
				if ( assigned == -1 ) continue;
				if ( normalize ) {
					const uint32_t same = literal > 0 ? positiveStamp : negativeStamp;
					const uint32_t opposite = literal > 0 ? negativeStamp : positiveStamp;
					if ( solver.mark[variable] == opposite ) {
						satisfied = true;
						break;
					}
					if ( solver.mark[variable] == same ) continue;
					solver.mark[variable] = same;
				}
				clause.literals[remaining] = literal;
				remaining ++;
			}
			if ( satisfied ) continue;
			clause.literals.resize(remaining);
			if ( remaining == 0 ) return 20;
			if ( remaining == 1 ) {
				const int literal = clause.literals[0];
				if ( solver.value[abs(literal)] == 0 ) solver.assign(literal, 0, -1);
				else if ( (literal > 0 ? solver.value[abs(literal)] : -solver.value[abs(literal)]) == -1 ) return 20;
				continue;
			}
			if ( output != i ) solver.clauseDB[output] = std::move(clause);
			output ++;
		}
		solver.clauseDB.resize(output, Clause(0));
		solver.origin_clauses = static_cast<int>(output);
		for ( int i = 0; i <= 2 * solver.vars; i ++ ) solver.watched_literals[i].clear();
		for ( int i = 1; i <= solver.vars; i ++ ) solver.reason[i] = -1;
		for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
			const Clause &clause = solver.clauseDB[i];
			solver.watched_literals[solver.vars - clause.literals[0]].push_back(WL(i, clause.literals[1]));
			solver.watched_literals[solver.vars - clause.literals[1]].push_back(WL(i, clause.literals[0]));
		}
		solver.propagated = 0;
		if ( solver.propagate() != -1 ) return 20;
		normalize = false;
		if ( trailBefore == solver.trail.size() ) return 0;
	}
}

static void addPreprocessOccurrences( PreprocessState &state, int clauseIdx ) {
	const Solver &solver = *state.solver;
	const Clause &clause = solver.clauseDB[clauseIdx];
	for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
		const size_t slot = static_cast<size_t>(solver.vars + clause.literals[i]);
		PreprocessOccurrence node;
		node.clauseIdx = clauseIdx;
		node.next = state.head[slot];
		state.head[slot] = static_cast<int>(state.nodes.size());
		state.nodes.push_back(node);
		state.count[slot] ++;
	}
}

static void deletePreprocessClause( PreprocessState &state, int clauseIdx ) {
	if ( state.deleted[clauseIdx] ) return;
	const Solver &solver = *state.solver;
	const Clause &clause = solver.clauseDB[clauseIdx];
	for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
		state.count[solver.vars + clause.literals[i]] --;
	}
	state.deleted[clauseIdx] = 1;
}

// 0 means no relation, 1 means subsumption, 2 means one resolvable literal.
static int preprocessSubsumption( PreprocessState &state, const Clause &small,
	const Clause &large, int &removeLiteral ) {
	if ( !preprocessCharge(state, small.literals.size() + large.literals.size()) ) return 0;
	size_t cursor = 0;
	removeLiteral = 0;
	for ( size_t i = 0; i < small.literals.size(); i ++ ) {
		const int literal = small.literals[i];
		while ( cursor < large.literals.size() && abs(large.literals[cursor]) < abs(literal) ) cursor ++;
		if ( cursor == large.literals.size() || abs(large.literals[cursor]) != abs(literal) ) return 0;
		if ( large.literals[cursor] != literal ) {
			if ( removeLiteral != 0 ) return 0;
			removeLiteral = large.literals[cursor];
		}
		cursor ++;
	}
	return removeLiteral == 0 ? 1 : 2;
}

static int runPreprocessSubsumption( PreprocessState &state, uint64_t stopWork ) {
	Solver &solver = *state.solver;
	for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
		if ( solver.preprocessingWork >= stopWork ) break;
		if ( state.deleted[i] ) continue;
		Clause &small = solver.clauseDB[i];
		if ( small.literals.size() > PREPROCESS_SUBSUMING_SIZE ) continue;
		int bestVariable = abs(small.literals[0]);
		uint64_t bestCount = UINT64_MAX;
		for ( size_t j = 0; j < small.literals.size(); j ++ ) {
			const int variable = abs(small.literals[j]);
			const uint64_t count = static_cast<uint64_t>(state.count[solver.vars + variable]) + state.count[solver.vars - variable];
			if ( count < bestCount ) {
				bestCount = count;
				bestVariable = variable;
			}
		}
		for ( int polarity = -1; polarity <= 1; polarity += 2 ) {
			int nodeIdx = state.head[solver.vars + polarity * bestVariable];
			while ( nodeIdx != -1 && solver.preprocessingWork < stopWork ) {
				if ( !preprocessCharge(state, 1) ) break;
				const PreprocessOccurrence &node = state.nodes[nodeIdx];
				const int target = node.clauseIdx;
				nodeIdx = node.next;
				if ( target == static_cast<int>(i) || state.deleted[target] ) continue;
				Clause &large = solver.clauseDB[target];
				if ( large.literals.size() < small.literals.size() ||
				     large.literals.size() > PREPROCESS_SUBSUMED_SIZE ) continue;
				int removeLiteral = 0;
				const int relation = preprocessSubsumption(state, small, large, removeLiteral);
				if ( relation == 1 ) {
					deletePreprocessClause(state, target);
					solver.preprocessingSubsumed ++;
				} else if ( relation == 2 ) {
					std::vector<int>::iterator position = std::find(large.literals.begin(), large.literals.end(), removeLiteral);
					large.literals.erase(position);
					state.count[solver.vars + removeLiteral] --;
					solver.preprocessingStrengthened ++;
					if ( large.literals.empty() ) return 20;
				}
			}
		}
	}
	return 0;
}

static bool gatherPreprocessClauses( PreprocessState &state, int literal,
	std::vector<int> &clauses ) {
	const Solver &solver = *state.solver;
	clauses.clear();
	int nodeIdx = state.head[solver.vars + literal];
	while ( nodeIdx != -1 ) {
		if ( !preprocessCharge(state, 1) ) return false;
		const PreprocessOccurrence &node = state.nodes[nodeIdx];
		nodeIdx = node.next;
		if ( state.deleted[node.clauseIdx] ) continue;
		const Clause &clause = solver.clauseDB[node.clauseIdx];
		if ( clause.literals.size() > PREPROCESS_MAX_RESOLVENT_SIZE ) return false;
		if ( !preprocessCharge(state, clause.literals.size()) ) return false;
		if ( !std::binary_search(clause.literals.begin(), clause.literals.end(), literal, preprocessLiteralLess) ) continue;
		clauses.push_back(node.clauseIdx);
		if ( clauses.size() > PREPROCESS_MAX_OCCURRENCES ) return false;
	}
	return true;
}

// A tautological resolvent returns 1; a complete resolvent returns 0.
// Returning -1 abandons the entire candidate without deleting its clauses.
static int makePreprocessResolvent( PreprocessState &state, const Clause &positive,
	const Clause &negative, int variable, std::vector<int> &resolvent ) {
	if ( !preprocessCharge(state, positive.literals.size() + negative.literals.size()) ) return -1;
	resolvent.clear();
	size_t p = 0, n = 0;
	while ( p < positive.literals.size() || n < negative.literals.size() ) {
		if ( p < positive.literals.size() && abs(positive.literals[p]) == variable ) {
			p ++;
			continue;
		}
		if ( n < negative.literals.size() && abs(negative.literals[n]) == variable ) {
			n ++;
			continue;
		}
		if ( p < positive.literals.size() && n < negative.literals.size() &&
		     abs(positive.literals[p]) == abs(negative.literals[n]) ) {
			if ( positive.literals[p] != negative.literals[n] ) return 1;
			resolvent.push_back(positive.literals[p]);
			p ++;
			n ++;
		} else if ( n == negative.literals.size() ||
		            (p < positive.literals.size() && abs(positive.literals[p]) < abs(negative.literals[n])) ) {
			resolvent.push_back(positive.literals[p]);
			p ++;
		} else {
			resolvent.push_back(negative.literals[n]);
			n ++;
		}
		if ( resolvent.size() > PREPROCESS_MAX_RESOLVENT_SIZE ) return -1;
	}
	return 0;
}

static int runPreprocessElimination( PreprocessState &state ) {
	Solver &solver = *state.solver;
	std::vector<int> positive, negative, resolvent;
	std::vector<std::vector<int> > resolvents;
	for ( int round = 0; round < PREPROCESS_ELIMINATION_ROUNDS; round ++ ) {
		const uint64_t eliminatedBefore = solver.preprocessingEliminated;
		for ( int variable = 1; variable <= solver.vars; variable ++ ) {
			if ( !preprocessCharge(state, 1) ) return 0;
			if ( solver.value[variable] != 0 || solver.eliminated[variable] ) continue;
			const size_t positives = state.count[solver.vars + variable];
			const size_t negatives = state.count[solver.vars - variable];
			if ( positives + negatives == 0 ) {
				solver.eliminated[variable] = 1;
				continue;
			}
			if ( positives > PREPROCESS_MAX_OCCURRENCES || negatives > PREPROCESS_MAX_OCCURRENCES ) continue;
			if ( !gatherPreprocessClauses(state, variable, positive) ||
			     !gatherPreprocessClauses(state, -variable, negative) ) continue;
			resolvents.clear();
			size_t removedLiterals = 0, generatedLiterals = 0;
			for ( size_t i = 0; i < positive.size(); i ++ ) removedLiterals += solver.clauseDB[positive[i]].literals.size();
			for ( size_t i = 0; i < negative.size(); i ++ ) removedLiterals += solver.clauseDB[negative[i]].literals.size();
			bool bounded = true;
			for ( size_t p = 0; p < positive.size() && bounded; p ++ ) {
				for ( size_t n = 0; n < negative.size(); n ++ ) {
					const int result = makePreprocessResolvent(state, solver.clauseDB[positive[p]],
						solver.clauseDB[negative[n]], variable, resolvent);
					if ( result == 1 ) continue;
					if ( result == -1 ) {
						bounded = false;
						break;
					}
					if ( resolvent.empty() ) return 20;
					generatedLiterals += resolvent.size();
					if ( resolvents.size() >= positive.size() + negative.size() ||
					     generatedLiterals > removedLiterals ||
					     generatedLiterals > PREPROCESS_GENERATED_LITERALS - state.generatedLiterals ||
					     generatedLiterals > state.nodeLimit - state.nodes.size() ) {
						bounded = false;
						break;
					}
					resolvents.push_back(resolvent);
				}
			}
			if ( !bounded ) continue;

			const bool savePositive = positive.size() <= negative.size();
			const std::vector<int> &savedClauses = savePositive ? positive : negative;
			size_t extensionSize = 0;
			for ( size_t i = 0; i < savedClauses.size(); i ++ ) extensionSize += solver.clauseDB[savedClauses[i]].literals.size();
			if ( extensionSize > PREPROCESS_EXTENSION_LITERALS - solver.eliminationLiterals.size() ||
			     resolvents.size() > static_cast<size_t>(INT_MAX) - solver.clauseDB.size() ) continue;

			// Commit only after all resolution and storage limits have passed.
			EliminationRecord record;
			record.variable = variable;
			record.defaultValue = savePositive ? -1 : 1;
			record.offset = solver.eliminationLiterals.size();
			for ( size_t i = 0; i < savedClauses.size(); i ++ ) {
				const Clause &clause = solver.clauseDB[savedClauses[i]];
				for ( size_t j = 0; j < clause.literals.size(); j ++ ) {
					if ( abs(clause.literals[j]) != variable ) solver.eliminationLiterals.push_back(clause.literals[j]);
				}
				solver.eliminationLiterals.push_back(0);
			}
			record.end = solver.eliminationLiterals.size();
			solver.eliminationRecords.push_back(record);
			solver.eliminated[variable] = 1;
			solver.preprocessingEliminated ++;
			for ( size_t i = 0; i < positive.size(); i ++ ) deletePreprocessClause(state, positive[i]);
			for ( size_t i = 0; i < negative.size(); i ++ ) deletePreprocessClause(state, negative[i]);
			for ( size_t i = 0; i < resolvents.size(); i ++ ) {
				const int index = static_cast<int>(solver.clauseDB.size());
				solver.clauseDB.push_back(Clause(0));
				solver.clauseDB.back().literals.swap(resolvents[i]);
				state.deleted.push_back(0);
				addPreprocessOccurrences(state, index);
				solver.preprocessingResolvents ++;
			}
			state.generatedLiterals += generatedLiterals;
		}
		if ( eliminatedBefore == solver.preprocessingEliminated ) break;
	}
	return 0;
}

int Solver::preprocess() {
	const std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
	eliminated.assign(static_cast<size_t>(vars) + 1, 0);
	if ( rebuildPreprocessRoot(*this, true) == 20 ) return finishPreprocessing(*this, start, 20);

	// The extra occurrence index is optional; large formulas retain CDCL.
	uint64_t literals = 0;
	for ( size_t i = 0; i < clauseDB.size(); i ++ ) literals += clauseDB[i].literals.size();
	const uint64_t slots = static_cast<uint64_t>(vars) * 2 + 1;
	const uint64_t fixedBytes = slots * (sizeof(int) + sizeof(uint32_t)) + clauseDB.size();
	const uint64_t initialBytes = fixedBytes + literals * sizeof(PreprocessOccurrence);
	if ( initialBytes > PREPROCESS_OCCURRENCE_BYTES || literals > static_cast<uint64_t>(INT_MAX) ) {
		return finishPreprocessing(*this, start, 0);
	}

	{
		PreprocessState state;
		state.solver = this;
		state.generatedLiterals = 0;
		const uint64_t spareNodes = (PREPROCESS_OCCURRENCE_BYTES - initialBytes) /
			(sizeof(PreprocessOccurrence) + sizeof(uint8_t));
		state.nodeLimit = static_cast<size_t>(literals) + static_cast<size_t>(std::min<uint64_t>(spareNodes, PREPROCESS_GENERATED_LITERALS));
		state.head.assign(static_cast<size_t>(slots), -1);
		state.count.assign(static_cast<size_t>(slots), 0);
		state.nodes.reserve(state.nodeLimit);
		state.deleted.reserve(clauseDB.size() + std::min<size_t>(PREPROCESS_GENERATED_LITERALS, state.nodeLimit - literals));
		state.deleted.assign(clauseDB.size(), 0);
		for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
			if ( clauseDB[i].literals.size() <= PREPROCESS_SUBSUMED_SIZE ) {
				std::sort(clauseDB[i].literals.begin(), clauseDB[i].literals.end(), preprocessLiteralLess);
			}
			addPreprocessOccurrences(state, static_cast<int>(i));
		}
		int result = runPreprocessSubsumption(state, PREPROCESS_SUBSUMPTION_WORK);
		if ( result == 0 ) result = runPreprocessElimination(state);
		if ( result == 0 ) {
			const uint64_t stopWork = std::min(PREPROCESS_WORK_LIMIT, preprocessingWork + PREPROCESS_SUBSUMPTION_WORK);
			result = runPreprocessSubsumption(state, stopWork);
		}
		if ( result == 20 ) return finishPreprocessing(*this, start, 20);
		for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
			if ( state.deleted[i] ) clauseDB[i].literals.clear();
		}
	}

	const int result = rebuildPreprocessRoot(*this, false);
	return finishPreprocessing(*this, start, result);
}

// Restore earlier variables after all variables in their residual clauses.
void Solver::extendModel() {
	for ( int variable = 1; variable <= vars; variable ++ ) {
		if ( value[variable] == 0 ) value[variable] = 1;
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
}
