#include "solver.h"
#include <algorithm>


struct LcmCandidate {
	int clauseIdx;
	int lbd;
	double activity;
	bool binary;
};


static bool compareLcmCandidates( const LcmCandidate &a, const LcmCandidate &b ) {
	if ( a.binary != b.binary ) return !a.binary;
	if ( a.binary ) return false;
	if ( a.lbd != b.lbd ) return a.lbd > b.lbd;
	return a.activity < b.activity;
}


static void detachLcmClause( Solver &solver, int clauseIdx ) {
	Clause &clause = solver.clauseDB[clauseIdx];
	if ( clause.literals.size() < 2 ) return;
	for ( int watch = 0; watch < 2; watch ++ ) {
		std::vector<WL> &list = solver.watched_literals[solver.vars - clause[watch]];
		size_t out = 0;
		for ( size_t i = 0; i < list.size(); i ++ ) {
			if ( list[i].clauseIdx != clauseIdx ) list[out ++] = list[i];
		}
		list.resize(out);
	}
}


static void attachLcmClause( Solver &solver, int clauseIdx ) {
	Clause &clause = solver.clauseDB[clauseIdx];
	solver.watched_literals[solver.vars - clause[0]].push_back(WL(clauseIdx, clause[1]));
	solver.watched_literals[solver.vars - clause[1]].push_back(WL(clauseIdx, clause[0]));
}


static void restoreLcmTrail( Solver &solver, size_t trailRecord ) {
	for ( size_t i = solver.trail.size(); i > trailRecord; i -- ) {
		const int variable = abs(solver.trail[i - 1]);
		solver.value[variable] = 0;
		solver.reason[variable] = -1;
		solver.level[variable] = 0;
	}
	solver.trail.resize(trailRecord);
	solver.propagated = static_cast<int>(trailRecord);
}


static int lcmValue( const Solver &solver, int literal ) {
	return literal > 0 ? solver.value[literal] : -solver.value[-literal];
}


static void markLcmReason( const Solver &solver, int clauseIdx, int skipVariable,
	std::vector<uint8_t> &seen, std::vector<int> &touched ) {
	const Clause &clause = solver.clauseDB[clauseIdx];
	for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
		const int variable = abs(clause.literals[i]);
		if ( variable == skipVariable || seen[variable] ) continue;
		seen[variable] = 1;
		touched.push_back(variable);
	}
}


// Resolve the temporary implication graph down to the negated assumptions.
static void analyzeLcmConflict( const Solver &solver, int conflictClause, int trueLiteral,
	size_t trailRecord, std::vector<uint8_t> &seen, std::vector<int> &touched,
	std::vector<int> &result ) {
	result.clear();
	touched.clear();
	if ( trueLiteral != 0 ) result.push_back(trueLiteral);
	if ( conflictClause >= 0 ) {
		markLcmReason(solver, conflictClause, abs(trueLiteral), seen, touched);
	}

	for ( size_t i = solver.trail.size(); i > trailRecord; i -- ) {
		const int literal = solver.trail[i - 1];
		const int variable = abs(literal);
		if ( !seen[variable] ) continue;
		const int clauseIdx = solver.reason[variable];
		if ( clauseIdx < 0 ) {
			result.push_back(-literal);
		} else {
			markLcmReason(solver, clauseIdx, variable, seen, touched);
		}
	}

	for ( size_t i = 0; i < touched.size(); i ++ ) seen[touched[i]] = 0;
}


static void simplifyLcmClause( Solver &solver, int clauseIdx,
	std::vector<uint8_t> &seen, std::vector<int> &touched ) {
	Clause &clause = solver.clauseDB[clauseIdx];
	const size_t trailRecord = solver.trail.size();
	std::vector<int> prefix;
	prefix.reserve(clause.literals.size());
	int conflictClause = -1;
	int trueLiteral = 0;

	for ( size_t i = 0; i < clause.literals.size(); i ++ ) {
		const int literal = clause.literals[i];
		const int literalValue = lcmValue(solver, literal);
		if ( literalValue == 0 ) {
			solver.assign(-literal, 0, -1);
			prefix.push_back(literal);
			conflictClause = solver.propagate();
			if ( conflictClause >= 0 ) break;
		} else if ( literalValue == 1 ) {
			prefix.push_back(literal);
			trueLiteral = literal;
			conflictClause = solver.reason[abs(literal)];
			break;
		}
	}

	if ( conflictClause >= 0 || trueLiteral != 0 ) {
		std::vector<int> explanation;
		analyzeLcmConflict(solver, conflictClause, trueLiteral, trailRecord,
			seen, touched, explanation);
		if ( explanation.size() < prefix.size() ) prefix.swap(explanation);
	}

	restoreLcmTrail(solver, trailRecord);
	clause.literals.swap(prefix);
	// Glucose 4.2.1 defaults to lcm-update=false: retain the original LBD.
}


// Called at the next root search entry after reduction; never force a restart.
int Solver::vivifyLearnts() {
	if ( !decVarInTrail.empty() ) return 30;
	if ( !withinBudget() ) return 30;
	lcmRuns ++;
	if ( propagate() >= 0 ) return 20;

	// simplifyAll removes satisfied original clauses before selecting learnts.
	for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
		Clause &clause = clauseDB[i];
		if ( clause.removed || clause.learntClause || clause.permanent ) continue;
		for ( size_t j = 0; j < clause.literals.size(); j ++ ) {
			if ( lcmValue(*this, clause[j]) == 1 ) {
				detachLcmClause(*this, static_cast<int>(i));
				clause.removed = true;
				break;
			}
		}
	}

	// Both permanent-clause vivification and the Chanseok path are disabled
	// in the reference implementation, including after automatic adaptation.
	if ( chanseokStrategy ) {
		compactClauses();
		return withinBudget() ? 0 : 30;
	}

	std::vector<LcmCandidate> candidates;
	for ( size_t i = 0; i < clauseDB.size(); i ++ ) {
		const Clause &clause = clauseDB[i];
		if ( clause.removed || !clause.learntClause || clause.permanent ) continue;
		LcmCandidate candidate;
		candidate.clauseIdx = static_cast<int>(i);
		candidate.lbd = clause.lbd;
		candidate.activity = clause.activity;
		candidate.binary = clause.literals.size() == 2;
		candidates.push_back(candidate);
	}
	std::sort(candidates.begin(), candidates.end(), compareLcmCandidates);
	std::vector<uint8_t> seen(static_cast<size_t>(vars) + 1, 0);
	std::vector<int> touched;

	for ( size_t i = 0; i < candidates.size(); i ++ ) {
		if ( !withinBudget() ) return 30;
		const int clauseIdx = candidates[i].clauseIdx;
		Clause &clause = clauseDB[clauseIdx];
		detachLcmClause(*this, clauseIdx);
		bool satisfied = false;
		size_t out = 0;
		for ( size_t j = 0; j < clause.literals.size(); j ++ ) {
			const int literalValue = lcmValue(*this, clause[j]);
			if ( literalValue == 1 ) satisfied = true;
			if ( literalValue != -1 ) clause[out ++] = clause[j];
		}
		if ( satisfied ) {
			clause.removed = true;
			continue;
		}
		clause.literals.resize(out);

		if ( clause.literals.size() > 1 && i >= candidates.size() / 2 && !clause.simplified ) {
			const size_t beforeSize = clause.literals.size();
			lcmTested ++;
			simplifyLcmClause(*this, clauseIdx, seen, touched);
			if ( clause.literals.size() < beforeSize ) {
				lcmReduced ++;
				lcmLiteralsRemoved += beforeSize - clause.literals.size();
			}
			clause.simplified = true;
		}

		if ( clause.literals.empty() ) return 20;
		if ( clause.literals.size() == 1 ) {
			const int literal = clause[0];
			clause.removed = true;
			if ( lcmValue(*this, literal) == -1 ) return 20;
			if ( lcmValue(*this, literal) == 0 ) assign(literal, 0, -1);
			if ( propagate() >= 0 ) return 20;
		} else {
			attachLcmClause(*this, clauseIdx);
		}
	}

	compactClauses();
	return withinBudget() ? 0 : 30;
}
