#include "solver.h"
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
