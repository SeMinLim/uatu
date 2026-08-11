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
		"\tunsigned int *lbdMark;                          // Decision-level marks for dynamic LBD\n\tunsigned int lbdStamp;\n",
		"\tunsigned int *lbdMark;                          // Decision-level marks for dynamic LBD\n\tunsigned int lbdStamp;\n\tunsigned char *minState;                         // Recursive-minimization state\n\tunsigned int *minMark;                           // Recursive-minimization stamps\n\tunsigned int minStamp;\n\tint recursiveMinimizeBudget;\n",
		"recursive minimization fields",
	)
	header = replace_once(
		header,
		"\tvoid updateClauseQuality( int cref );                      // Update usage activity and dynamic LBD\n    \tint  analyze( int cref, int &backtrack_level, int &lbd ); // Conflict analysis\n",
		"\tvoid updateClauseQuality( int cref );                      // Update usage activity and dynamic LBD\n\tbool recursiveRedundant( int variable, unsigned int membershipStamp, int &budget );\n    \tint  analyze( int cref, int &backtrack_level, int &lbd ); // Conflict analysis\n",
		"recursive minimization declaration",
	)

	solver = replace_once(
		solver,
		"#ifndef UATU_PROFILE_BCP\n#define UATU_PROFILE_BCP 0\n#endif\n",
		"#ifndef UATU_PROFILE_BCP\n#define UATU_PROFILE_BCP 0\n#endif\n\n#ifndef UATU_REDUCE_BACKTRACK\n#define UATU_REDUCE_BACKTRACK 1\n#endif\n",
		"reduce backtrack switch",
	)
	solver = replace_once(
		solver,
		"        lbdMark = new unsigned int[vars + 1];\n        activity = new double[vars + 1];\n",
		"        lbdMark = new unsigned int[vars + 1];\n        minState = new unsigned char[vars + 1];\n        minMark = new unsigned int[vars + 1];\n        activity = new double[vars + 1];\n",
		"recursive minimization allocation",
	)
	solver = replace_once(
		solver,
		"        lbdStamp = 0;\n        fast_lbd_sum",
		"        lbdStamp = 0;\n        minStamp = 0;\n        recursiveMinimizeBudget = 0;\n        fast_lbd_sum",
		"recursive minimization initialization",
	)
	solver = replace_once(
		solver,
		"        var_inc = 1;\n        var_decay = 0.8;\n        clause_inc",
		"        var_inc = 1;\n        var_decay = 0.8;\n        if ( const char *env = getenv(\"UATU_VAR_DECAY\") ) {\n                const double parsed = atof(env);\n                if ( parsed > 0.0 && parsed < 1.0 ) var_decay = parsed;\n        }\n        clause_inc",
		"variable decay override",
	)
	solver = replace_once(
		solver,
		"        if ( const char *env = getenv(\"UATU_CLAUSE_DECAY\") ) {\n                const double parsed = atof(env);\n                if ( parsed > 0.0 && parsed < 1.0 ) clause_decay = parsed;\n        }\n        rephase_inc",
		"        if ( const char *env = getenv(\"UATU_CLAUSE_DECAY\") ) {\n                const double parsed = atof(env);\n                if ( parsed > 0.0 && parsed < 1.0 ) clause_decay = parsed;\n        }\n        if ( const char *env = getenv(\"UATU_RECURSIVE_MIN_BUDGET\") ) {\n                const int parsed = atoi(env);\n                if ( parsed > 0 ) recursiveMinimizeBudget = parsed;\n        }\n        rephase_inc",
		"recursive minimization environment",
	)
	solver = replace_once(
		solver,
		"        lbdMark[0] = 0;\n        for ( int i = 1; i <= vars; i ++ ) {\n",
		"        lbdMark[0] = 0;\n        minState[0] = 0;\n        minMark[0] = 0;\n        for ( int i = 1; i <= vars; i ++ ) {\n",
		"recursive minimization root state",
	)
	solver = replace_once(
		solver,
		"                lbdMark[i] = 0;\n                activity[i] = 0.0;\n",
		"                lbdMark[i] = 0;\n                minState[i] = 0;\n                minMark[i] = 0;\n                activity[i] = 0.0;\n",
		"recursive minimization variable state",
	)

	helper = r'''
// Check whether a learnt literal is recursively redundant
bool Solver::recursiveRedundant( int variable, unsigned int membershipStamp, int &budget ) {
        if ( budget <= 0 ) return false;
        if ( minMark[variable] == minStamp ) {
                return minState[variable] == 2;
        }

        budget --;
        minMark[variable] = minStamp;
        minState[variable] = 1;

        const int reasonClause = reason[variable];
        if ( reasonClause < 0 ) {
                minState[variable] = 3;
                return false;
        }

        const Clause &reasonData = clauseDB[reasonClause];
        for ( int literal : reasonData.literals ) {
                const int reasonVariable = abs(literal);
                if ( reasonVariable == variable || level[reasonVariable] == 0 ) continue;
                if ( mark[reasonVariable] == membershipStamp ) continue;
                if ( minMark[reasonVariable] == minStamp && minState[reasonVariable] == 1 ) continue;
                if ( !recursiveRedundant(reasonVariable, membershipStamp, budget) ) {
                        minState[variable] = 3;
                        return false;
                }
        }

        minState[variable] = 2;
        return true;
}

'''
	solver = replace_once(
		solver,
		"// Conflict analysis\nint Solver::analyze",
		helper + "// Conflict analysis\nint Solver::analyze",
		"recursive minimization helper",
	)

	oldBlock = r'''        // Non-recursive, one-step reason minimization.
        if ( learnt.size() > 1 ) {
                ++time_stamp;
                const int membershipStamp = time_stamp;
                for ( int literal : learnt ) mark[abs(literal)] = membershipStamp;

                int out = 1;
                for ( int i = 1; i < static_cast<int>(learnt.size()); i ++ ) {
                        const int literal = learnt[i];
                        const int variable = abs(literal);
                        const int reasonClause = reason[variable];
                        bool removable = reasonClause >= 0;

                        if ( removable ) {
                                const Clause &reasonData = clauseDB[reasonClause];
                                for ( int q : reasonData.literals ) {
                                        const int qvar = abs(q);
                                        if ( qvar == variable || level[qvar] == 0 ) continue;
                                        if ( mark[qvar] != membershipStamp ) {
                                                removable = false;
                                                break;
                                        }
                                }
                        }

                        if ( removable ) ++minimizedLiterals;
                        else learnt[out++] = literal;
                }
                learnt.resize(out);
        }
'''
	newBlock = r'''        // One-step or budgeted recursive reason minimization.
        if ( learnt.size() > 1 ) {
                ++time_stamp;
                const unsigned int membershipStamp = static_cast<unsigned int>(time_stamp);
                for ( int literal : learnt ) mark[abs(literal)] = membershipStamp;

                minStamp ++;
                if ( minStamp == 0 ) {
                        for ( int i = 0; i <= vars; i ++ ) minMark[i] = 0;
                        minStamp = 1;
                }

                int out = 1;
                for ( int i = 1; i < static_cast<int>(learnt.size()); i ++ ) {
                        const int literal = learnt[i];
                        const int variable = abs(literal);
                        bool removable = false;

                        if ( recursiveMinimizeBudget > 0 ) {
                                int budget = recursiveMinimizeBudget;
                                removable = recursiveRedundant(variable, membershipStamp, budget);
                        } else {
                                const int reasonClause = reason[variable];
                                removable = reasonClause >= 0;
                                if ( removable ) {
                                        const Clause &reasonData = clauseDB[reasonClause];
                                        for ( int q : reasonData.literals ) {
                                                const int qvar = abs(q);
                                                if ( qvar == variable || level[qvar] == 0 ) continue;
                                                if ( mark[qvar] != membershipStamp ) {
                                                        removable = false;
                                                        break;
                                                }
                                        }
                                }
                        }

                        if ( removable ) minimizedLiterals ++;
                        else learnt[out++] = literal;
                }
                learnt.resize(out);
        }
'''
	solver = replace_once(solver, oldBlock, newBlock, "minimization block")
	solver = replace_once(
		solver,
		"        // The only heuristic that performs a root backtrack.\n        backtrack(0);\n        reduces = 0;\n",
		"        // Optional root backtrack before clause-database reduction.\n#if UATU_REDUCE_BACKTRACK\n        backtrack(0);\n#endif\n        reduces = 0;\n",
		"reduction backtrack switch",
	)

	headerPath.write_text(header)
	solverPath.write_text(solver)


if __name__ == "__main__":
	main()
