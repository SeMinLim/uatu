from pathlib import Path


def replace_once(path, old, new):
	text = Path(path).read_text()
	if old not in text:
		raise SystemExit(f"missing replacement anchor in {path}: {old[:120]!r}")
	Path(path).write_text(text.replace(old, new, 1))


def replace_region(path, start, end, replacement):
	text = Path(path).read_text()
	start_pos = text.find(start)
	if start_pos < 0:
		raise SystemExit(f"missing start anchor in {path}: {start!r}")
	end_pos = text.find(end, start_pos)
	if end_pos < 0:
		raise SystemExit(f"missing end anchor in {path}: {end!r}")
	Path(path).write_text(text[:start_pos] + replacement + text[end_pos:])


solver_source = "cpu/ver_5/solver.cpp"
solver_header = "cpu/ver_5/solver.h"
makefile = "cpu/ver_5/Makefile"
root_readme = "README.md"
version_readme = "cpu/ver_5/README.md"

replace_once(
	solver_source,
	'#include "solver.h"\n#include <algorithm>',
	'#include "solver.h"\n#include "recursive.h"\n\n#include <algorithm>',
)

replace_region(
	solver_source,
	"        // Non-recursive, one-step reason minimization.\n",
	"        ++time_stamp;\n        lbd = 0;",
	"        // Recursive reason-graph minimization.\n"
	"        minimizeLearnedClauseRecursive(*this);\n\n",
)

replace_once(
	solver_header,
	"\tunsigned int *lbdMark;                          // Decision-level marks for dynamic LBD\n",
	"\tunsigned int *lbdMark;                          // Marks for dynamic LBD and recursive minimization\n",
)

replace_once(
	makefile,
	"SOURCES := solver.cpp main.cpp\nHEADERS := solver.h\n",
	"SOURCES := solver.cpp recursive.cpp main.cpp\nHEADERS := solver.h recursive.h\n",
)

replace_once(
	root_readme,
	"| `cpu/ver_5` | Ver. 3 with CORE, TIER2, and LOCAL learned-clause management |",
	"| `cpu/ver_5` | Ver. 3 with recursive learned-clause minimization and CORE, TIER2, and LOCAL learned-clause management |",
)

Path(version_readme).write_text(
	"# Uatu Ver. 5\n\n"
	"Recursive learned-clause minimization and tiered clause management built directly on Ver. 3.\n\n"
	"## Architecture\n\n"
	"- Retains the Ver. 3 BCP, First-UIP learning, VSIDS branching, usage-aware clause activity, dynamic LBD updates, and search-control pipeline.\n"
	"- Replaces one-step minimization with iterative recursive traversal of the implication-graph reason closure.\n"
	"- Removes a learned literal only when every non-root antecedent is already represented by the learned clause or is recursively redundant.\n"
	"- Keeps learned clauses with LBD at most 3 permanently in the CORE tier.\n"
	"- Protects recently used clauses with LBD from 4 through 6 in TIER2 and demotes stale clauses to LOCAL.\n"
	"- Deletes the lower-activity half of unlocked LOCAL clauses at each reduction.\n"
	"- Does not enable CHB branching.\n"
)

Path("cpu/ver_5/recursive.h").write_text(
	"#ifndef UATU_VER5_RECURSIVE_H\n"
	"#define UATU_VER5_RECURSIVE_H\n\n"
	"class Solver;\n\n"
	"void minimizeLearnedClauseRecursive( Solver &solver );\n\n"
	"#endif\n"
)

Path("cpu/ver_5/recursive.cpp").write_text(r'''#include "solver.h"
#include "recursive.h"

#include <climits>


typedef struct MinimizeFrame {
	int variable;
	size_t nextLiteral;
}MinimizeFrame;


// Mark the current reason path as failed
static void markReasonPathFailed( Solver &solver,
				 unsigned int visitingStamp,
				 unsigned int failedStamp,
				 std::vector<int> &touched ) {
	for ( int variable : touched ) {
		if ( solver.lbdMark[variable] == visitingStamp ) {
			solver.lbdMark[variable] = failedStamp;
		}
	}
}

// Check whether the complete reason closure is redundant
static bool recursivelyRedundant( Solver &solver,
				  int rootVariable,
				  int membershipStamp,
				  unsigned int visitingStamp,
				  unsigned int redundantStamp,
				  unsigned int failedStamp,
				  std::vector<MinimizeFrame> &stack,
				  std::vector<int> &touched ) {
	if ( solver.lbdMark[rootVariable] == redundantStamp ) return true;
	if ( solver.lbdMark[rootVariable] == failedStamp ) return false;

	const int rootReason = solver.reason[rootVariable];
	if ( rootReason < 0 ||
	     rootReason >= static_cast<int>(solver.clauseDB.size()) ) return false;

	stack.clear();
	touched.clear();
	stack.push_back({rootVariable, 0});

	while ( !stack.empty() ) {
		MinimizeFrame &frame = stack.back();
		const int variable = frame.variable;

		if ( solver.lbdMark[variable] == redundantStamp ) {
			stack.pop_back();
			continue;
		}
		if ( solver.lbdMark[variable] == failedStamp ) {
			markReasonPathFailed(solver, visitingStamp, failedStamp, touched);
			return false;
		}

		if ( frame.nextLiteral == 0 ) {
			if ( solver.lbdMark[variable] == visitingStamp ) {
				markReasonPathFailed(solver, visitingStamp, failedStamp, touched);
				return false;
			}
			solver.lbdMark[variable] = visitingStamp;
			touched.push_back(variable);
		}

		const int reasonClause = solver.reason[variable];
		if ( reasonClause < 0 ||
		     reasonClause >= static_cast<int>(solver.clauseDB.size()) ) {
			markReasonPathFailed(solver, visitingStamp, failedStamp, touched);
			return false;
		}

		const Clause &reasonData = solver.clauseDB[reasonClause];
		bool descended = false;
		while ( frame.nextLiteral < reasonData.literals.size() ) {
			const int qvar = abs(reasonData.literals[frame.nextLiteral ++]);
			if ( qvar == variable || solver.level[qvar] == 0 ) continue;
			if ( solver.mark[qvar] == membershipStamp ) continue;
			if ( solver.lbdMark[qvar] == redundantStamp ) continue;

			const int qreason = solver.reason[qvar];
			if ( qreason < 0 ||
			     qreason >= static_cast<int>(solver.clauseDB.size()) ||
			     solver.lbdMark[qvar] == failedStamp ||
			     solver.lbdMark[qvar] == visitingStamp ) {
				markReasonPathFailed(solver, visitingStamp, failedStamp, touched);
				return false;
			}

			stack.push_back({qvar, 0});
			descended = true;
			break;
		}

		if ( descended ) continue;

		solver.lbdMark[variable] = redundantStamp;
		stack.pop_back();
	}

	return true;
}

// Minimize a learned clause through recursive reason traversal
void minimizeLearnedClauseRecursive( Solver &solver ) {
	if ( solver.learnt.size() <= 1 ) return;

	solver.time_stamp ++;
	const int membershipStamp = solver.time_stamp;
	for ( int literal : solver.learnt ) {
		solver.mark[abs(literal)] = membershipStamp;
	}

	if ( solver.lbdStamp >= UINT_MAX - 3 ) {
		for ( int i = 0; i <= solver.vars; i ++ ) solver.lbdMark[i] = 0;
		solver.lbdStamp = 0;
	}
	const unsigned int visitingStamp = ++solver.lbdStamp;
	const unsigned int redundantStamp = ++solver.lbdStamp;
	const unsigned int failedStamp = ++solver.lbdStamp;

	std::vector<MinimizeFrame> stack;
	std::vector<int> touched;
	stack.reserve(32);
	touched.reserve(32);

	int out = 1;
	for ( int i = 1; i < static_cast<int>(solver.learnt.size()); i ++ ) {
		const int literal = solver.learnt[i];
		const int variable = abs(literal);
		const bool removable = recursivelyRedundant(
			solver,
			variable,
			membershipStamp,
			visitingStamp,
			redundantStamp,
			failedStamp,
			stack,
			touched
		);

		if ( removable ) solver.minimizedLiterals ++;
		else solver.learnt[out ++] = literal;
	}
	solver.learnt.resize(out);
}
''')
