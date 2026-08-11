#!/usr/bin/env python3

import argparse
import shutil
from pathlib import Path


def replace_once(text, old, new, label):
	if old not in text:
		raise RuntimeError(f"patch point not found: {label}")
	return text.replace(old, new, 1)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("source")
	parser.add_argument("output")
	args = parser.parse_args()

	sourceDir = Path(args.source)
	outputDir = Path(args.output)
	if outputDir.exists():
		shutil.rmtree(outputDir)
	shutil.copytree(sourceDir, outputDir)

	headerPath = outputDir / "solver.h"
	solverPath = outputDir / "solver.cpp"
	header = headerPath.read_text()
	solver = solverPath.read_text()

	header = replace_once(
		header,
		"\tvoid update( int x ) { up(pos[x]); }\n",
		"\tvoid update( int x ) {\n\t\tint position = pos[x];\n\t\tup(position);\n\t\tdown(pos[x]);\n\t}\n",
		"bidirectional heap update",
	)
	header = replace_once(
		header,
		"\t// The number of conflict-analysis uses\n\tuint32_t useCount;\n    \t// Literals in a clause\n",
		"\t// The number of conflict-analysis uses\n\tuint32_t useCount;\n\t// The most recent conflict that used this clause\n\tint lastUsedConflict;\n    \t// Literals in a clause\n",
		"clause last-use field",
	)
	header = replace_once(
		header,
		"    \tClause( int sz ): lbd(0), activity(0.0), useCount(0) { literals.resize(sz); }\n",
		"    \tClause( int sz ): lbd(0), activity(0.0), useCount(0), lastUsedConflict(0) { literals.resize(sz); }\n",
		"clause constructor",
	)
	header = replace_once(
		header,
		"    \tdouble *activity;                              // The variables' score for VSIDS\n\tdouble var_inc, var_decay;                       // Parameter for VSIDS\n",
		"    \tdouble *activity;                              // Variable branching score\n\tdouble var_inc, var_decay;                       // Parameters for VSIDS\n\tint branchingPolicy;                             // 0: VSIDS, 1: CHB\n\tint *chbLastConflict;                            // Last conflict involving each variable\n\tint chbAction;                                   // First trail position awaiting CHB update\n\tdouble chbStep;                                  // CHB exponential averaging step\n\tbool tieredClauses;                              // Enable core/tier2/local retention\n",
		"CHB fields",
	)
	header = replace_once(
		header,
		"\tvoid update_score( int var, double coeff );               // Update variable activity\n\tvoid bumpClauseActivity",
		"\tvoid update_score( int var, double coeff );               // Update VSIDS activity\n\tvoid updateCHBScore( int var, double multiplier );          // Update CHB score\n\tvoid updateAssignedCHB( bool conflict );                    // Reward newly assigned variables\n\tvoid bumpClauseActivity",
		"CHB declarations",
	)

	solver = replace_once(
		solver,
		"        reason = new int[vars + 1];\n        level = new int[vars + 1];\n",
		"        reason = new int[vars + 1];\n        level = new int[vars + 1];\n        chbLastConflict = new int[vars + 1];\n",
		"CHB allocation",
	)
	solver = replace_once(
		solver,
		"        var_inc = 1;\n        var_decay = 0.8;\n",
		"        var_inc = 1;\n        var_decay = 0.8;\n        branchingPolicy = 0;\n        chbAction = 0;\n        chbStep = 0.4;\n        tieredClauses = false;\n        if ( const char *env = getenv(\"UATU_BRANCHING\") ) {\n                if ( strcmp(env, \"chb\") == 0 ) branchingPolicy = 1;\n        }\n        if ( const char *env = getenv(\"UATU_TIERED_CLAUSES\") ) {\n                tieredClauses = atoi(env) != 0;\n        }\n",
		"CHB configuration",
	)
	solver = replace_once(
		solver,
		"                reason[i] = level[i] = mark[i] = 0;\n",
		"                reason[i] = level[i] = mark[i] = 0;\n                chbLastConflict[i] = 0;\n",
		"CHB variable initialization",
	)

	helper = r'''
// Update the exponential recency-weighted CHB score
void Solver::updateCHBScore( int var, double multiplier ) {
        int age = conflicts - chbLastConflict[var] + 1;
        if ( age < 1 ) age = 1;

        const double reward = multiplier / static_cast<double>(age);
        activity[var] = chbStep * reward + (1.0 - chbStep) * activity[var];
        if ( vsids.inHeap(var) ) vsids.update(var);
}

// Reward variables assigned since the previous propagation event
void Solver::updateAssignedCHB( bool conflict ) {
        if ( branchingPolicy != 1 ) return;
        if ( chbAction > static_cast<int>(trail.size()) ) chbAction = trail.size();

        const double multiplier = conflict ? 1.0 : 0.9;
        for ( int i = chbAction; i < static_cast<int>(trail.size()); i ++ ) {
                updateCHBScore(abs(trail[i]), multiplier);
        }
        chbAction = trail.size();
}

'''
	solver = replace_once(
		solver,
		"// Update learnt-clause activity\nvoid Solver::bumpClauseActivity",
		helper + "// Update learnt-clause activity\nvoid Solver::bumpClauseActivity",
		"CHB helper functions",
	)
	solver = replace_once(
		solver,
		"        Clause &clause = clauseDB[cref];\n        const int currentLBD = calculateClauseLBD(clause);\n",
		"        Clause &clause = clauseDB[cref];\n        clause.lastUsedConflict = conflicts;\n        const int currentLBD = calculateClauseLBD(clause);\n",
		"clause last-use update",
	)
	solver = replace_once(
		solver,
		"                        update_score(variable, 0.5);\n                        bump.push_back(variable);\n",
		"                        if ( branchingPolicy == 0 ) update_score(variable, 0.5);\n                        else chbLastConflict[variable] = conflicts;\n                        bump.push_back(variable);\n",
		"branching update during analysis",
	)
	solver = replace_once(
		solver,
		"        // Original second-stage bump retained after the ablation trial.\n        for ( int variable : bump ) {\n                if ( level[variable] >= backtrackLevel - 1 ) update_score(variable, 1.0);\n        }\n",
		"        // Original second-stage bump is used only by VSIDS.\n        if ( branchingPolicy == 0 ) {\n                for ( int variable : bump ) {\n                        if ( level[variable] >= backtrackLevel - 1 ) update_score(variable, 1.0);\n                }\n        }\n",
		"VSIDS-only second-stage bump",
	)
	solver = replace_once(
		solver,
		"\t\ttrail.resize(propagated);\n\t\tdecVarInTrail.resize(backtrackLevel);\n",
		"\t\ttrail.resize(propagated);\n\t\tdecVarInTrail.resize(backtrackLevel);\n                if ( branchingPolicy == 1 && chbAction > propagated ) chbAction = propagated;\n",
		"CHB backtrack action",
	)
	solver = replace_once(
		solver,
		"        for ( int i = origin_clauses; i < oldSize; i ++ ) {\n                if ( !locked[i] && clauseDB[i].lbd >= 5 ) candidates.push_back(i);\n        }\n",
		"        for ( int i = origin_clauses; i < oldSize; i ++ ) {\n                if ( locked[i] ) continue;\n                if ( tieredClauses ) {\n                        const bool core = clauseDB[i].lbd <= 3;\n                        const bool recentTier = clauseDB[i].lbd <= 6 &&\n                                conflicts - clauseDB[i].lastUsedConflict <= 30000;\n                        if ( core || recentTier ) continue;\n                        candidates.push_back(i);\n                } else if ( clauseDB[i].lbd >= 5 ) {\n                        candidates.push_back(i);\n                }\n        }\n",
		"tiered clause candidates",
	)
	solver = replace_once(
		solver,
		"                const int conflictClause = propagate();\n                if ( conflictClause != -1 ) {\n",
		"                const int conflictClause = propagate();\n                updateAssignedCHB(conflictClause != -1);\n                if ( conflictClause != -1 ) {\n",
		"CHB propagation feedback",
	)
	solver = replace_once(
		solver,
		"                                clauseDB[learnedClause].lbd = lbd;\n                                assign(learnt[0], backtrackLevel, learnedClause);\n",
		"                                clauseDB[learnedClause].lbd = lbd;\n                                clauseDB[learnedClause].lastUsedConflict = conflicts;\n                                assign(learnt[0], backtrackLevel, learnedClause);\n",
		"learnt clause last-use initialization",
	)
	solver = replace_once(
		solver,
		"                        var_inc *= 1.0 / var_decay;\n                        clause_inc *= 1.0 / clause_decay;\n",
		"                        if ( branchingPolicy == 0 ) {\n                                var_inc *= 1.0 / var_decay;\n                        } else if ( chbStep > 0.06 ) {\n                                chbStep -= 0.000001;\n                                if ( chbStep < 0.06 ) chbStep = 0.06;\n                        }\n                        clause_inc *= 1.0 / clause_decay;\n",
		"branching decay update",
	)

	headerPath.write_text(header)
	solverPath.write_text(solver)


if __name__ == "__main__":
	main()
