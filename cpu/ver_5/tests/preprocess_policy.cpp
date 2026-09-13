#include "../preprocess.cpp"
#include <cassert>


static void makePreprocessState( Solver &solver, PreprocessState &state ) {
	state.solver = &solver;
	state.occurs.resize(static_cast<size_t>(solver.vars) + 1);
	state.literalCount.assign(static_cast<size_t>(solver.vars) * 2 + 1, 0);
	state.abstraction.assign(solver.clauseDB.size(), 0);
	state.queued.assign(solver.clauseDB.size(), 0);
	state.touched.assign(static_cast<size_t>(solver.vars) + 1, 0);
	state.position.assign(static_cast<size_t>(solver.vars) + 1, -1);
	for ( int variable = 1; variable <= solver.vars; variable ++ ) updateEliminationHeap(state, variable, true);
	for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) {
		indexPreprocessClause(state, static_cast<int>(i), true);
		queuePreprocessClause(state, static_cast<int>(i));
	}
}

static void initializeFormula( Solver &solver, int vars, const std::vector<std::vector<int> > &formula ) {
	solver.vars = vars;
	solver.clauses = static_cast<int>(formula.size());
	solver.initialize();
	for ( size_t i = 0; i < formula.size(); i ++ ) {
		std::vector<int> clause = formula[i];
		solver.add_clause(clause);
	}
	solver.origin_clauses = static_cast<int>(formula.size());
}

static bool satisfiesFormula( const Solver &solver, const std::vector<std::vector<int> > &formula ) {
	for ( size_t i = 0; i < formula.size(); i ++ ) {
		bool satisfied = false;
		for ( size_t j = 0; j < formula[i].size(); j ++ ) {
			const int literal = formula[i][j];
			if ( (literal > 0 ? solver.value[literal] : -solver.value[-literal]) == 1 ) satisfied = true;
		}
		if ( !satisfied ) return false;
	}
	return true;
}

int main() {
	// A 3 by 3 cross product exceeds grow=0 (nine resolvents replace six clauses).
	{
		Solver solver;
		initializeFormula(solver, 7, {{1, 2}, {1, 3}, {1, 4}, {-1, 5}, {-1, 6}, {-1, 7}});
		PreprocessState state;
		makePreprocessState(solver, state);
		assert(eliminatePreprocessVariable(state, 1) == 0);
		assert(!solver.eliminated[1]);
		assert(solver.eliminationRecords.empty());
	}
	// The resolvent length boundary is inclusive at twenty literals.
	for ( int length = 20; length <= 21; length ++ ) {
		Solver solver;
		std::vector<int> positive{1}, negative{-1};
		for ( int variable = 2; variable <= 11; variable ++ ) positive.push_back(variable);
		for ( int variable = 12; variable <= length + 1; variable ++ ) negative.push_back(variable);
		initializeFormula(solver, 22, {positive, negative});
		PreprocessState state;
		makePreprocessState(solver, state);
		assert(eliminatePreprocessVariable(state, 1) == 0);
		assert(bool(solver.eliminated[1]) == (length == 20));
	}
	// A tautological cross product contributes neither a resolvent nor its length.
	{
		Solver solver;
		initializeFormula(solver, 2, {{1, 2}, {-1, -2}});
		PreprocessState state;
		makePreprocessState(solver, state);
		assert(eliminatePreprocessVariable(state, 1) == 0);
		assert(solver.eliminated[1]);
		assert(solver.preprocessingResolvents == 0);
		for ( int phase = -1; phase <= 1; phase += 2 ) {
			solver.value[2] = static_cast<int8_t>(phase);
			assert(solver.extendModel());
			assert(solver.value[1] == -phase);
		}
	}
	// Subsumption skips target lengths >=1000, while SSR queues the strengthened clause.
	{
		Solver solver;
		std::vector<int> below, boundary;
		for ( int literal = 1; literal <= 999; literal ++ ) below.push_back(literal);
		for ( int literal = 1; literal <= 1000; literal ++ ) boundary.push_back(literal);
		initializeFormula(solver, 1000, {{1, 2}, below, boundary});
		PreprocessState state;
		makePreprocessState(solver, state);
		assert(backwardPreprocessSubsumption(state) == 0);
		assert(solver.clauseDB[1].removed);
		assert(!solver.clauseDB[2].removed);
	}
	{
		Solver solver;
		initializeFormula(solver, 3, {{1, 2}, {-1, 2, 3}});
		PreprocessState state;
		makePreprocessState(solver, state);
		assert(backwardPreprocessSubsumption(state) == 0);
		assert(solver.preprocessingStrengthened == 1);
		assert(solver.clauseDB[1].literals.size() == 2);
		assert(std::find(solver.clauseDB[1].literals.begin(), solver.clauseDB[1].literals.end(), -1) == solver.clauseDB[1].literals.end());
	}
	// Every satisfying reduced assignment reconstructs an original satisfying model.
	{
		const std::vector<std::vector<int> > original{{1, 2}, {-1, 3}, {-2, 4}, {-3, -4}};
		Solver solver;
		initializeFormula(solver, 4, original);
		assert(solver.preprocess() == 0);
		const std::vector<int8_t> root(solver.value, solver.value + solver.vars + 1);
		unsigned checked = 0;
		for ( unsigned mask = 0; mask < 16; mask ++ ) {
			bool rootConsistent = true;
			for ( int variable = 1; variable <= solver.vars; variable ++ ) {
				const int phase = (mask & (1U << (variable - 1))) != 0 ? 1 : -1;
				if ( !solver.eliminated[variable] && root[variable] != 0 && root[variable] != phase ) rootConsistent = false;
				solver.value[variable] = static_cast<int8_t>(phase);
			}
			if ( !rootConsistent ) continue;
			std::vector<std::vector<int> > reduced;
			for ( size_t i = 0; i < solver.clauseDB.size(); i ++ ) reduced.push_back(solver.clauseDB[i].literals);
			if ( !satisfiesFormula(solver, reduced) ) continue;
			assert(solver.extendModel());
			assert(satisfiesFormula(solver, original));
			checked ++;
		}
		assert(checked != 0);
	}
	printf( "Preprocessing policy and model reconstruction checks passed.\n" );
	return 0;
}
