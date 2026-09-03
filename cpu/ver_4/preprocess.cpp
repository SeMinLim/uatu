#include "preprocess.h"

#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <deque>
#include <set>
#include <utility>


#define PREPROCESS_MAX_SOURCE_CLAUSE 32
#define PREPROCESS_MAX_TARGET_CLAUSE 1000
#define PREPROCESS_MAX_SUBSUMPTION_CHECKS 2000000
#define PREPROCESS_MAX_BVE_OCCURRENCE 64
#define PREPROCESS_MAX_BVE_PAIRS 4096
#define PREPROCESS_MAX_RESOLVENT_LENGTH 20
#define PREPROCESS_MAX_AUXILIARY_BYTES (512ULL * 1024ULL * 1024ULL)


typedef struct ClauseOrder {
	bool operator () ( const std::vector<int> &left,
			  const std::vector<int> &right ) const {
		return std::lexicographical_compare(
			left.begin(), left.end(),
			right.begin(), right.end(),
			literalLess
		);
	}

	static bool literalLess( int left, int right ) {
		const int leftVariable = abs(left);
		const int rightVariable = abs(right);
		if ( leftVariable != rightVariable ) return leftVariable < rightVariable;
		return left < right;
	}
}ClauseOrder;


// Map a signed literal to an occurrence-list index
static inline int literalIndex( int literal ) {
	const int variable = abs(literal);
	return literal > 0 ? variable * 2 : variable * 2 + 1;
}

// Check whether a sorted clause contains a literal
static bool containsLiteral( const std::vector<int> &clause, int literal ) {
	return std::binary_search(
		clause.begin(),
		clause.end(),
		literal,
		ClauseOrder::literalLess
	);
}

// Normalize one input clause
static int normalizeClause( int variableCount,
			    std::vector<int> &clause,
			    PreprocessResult &result ) {
	std::sort(clause.begin(), clause.end(), ClauseOrder::literalLess);

	int out = 0;
	for ( int literal : clause ) {
		const int variable = abs(literal);
		if ( variable == 0 || variable > variableCount ) return 30;

		if ( out > 0 && clause[out - 1] == literal ) {
			result.removedDuplicateLiterals ++;
			continue;
		}
		if ( out > 0 && abs(clause[out - 1]) == variable ) {
			result.removedTautologies ++;
			return 1;
		}
		clause[out ++] = literal;
	}
	clause.resize(out);
	return clause.empty() ? 20 : 0;
}

// Remove deleted clauses from the formula
static void compactFormula( std::vector<std::vector<int>> &formula,
			    const std::vector<unsigned char> &alive ) {
	int out = 0;
	for ( int i = 0; i < static_cast<int>(formula.size()); i ++ ) {
		if ( !alive[i] ) continue;
		if ( out != i ) formula[out] = std::move(formula[i]);
		out ++;
	}
	formula.resize(out);
}

// Simplify the formula with root-level unit assignments
static int propagateUnits( int variableCount,
			   std::vector<std::vector<int>> &formula,
			   PreprocessResult &result ) {
	std::vector<unsigned char> alive(formula.size(), 1);
	std::deque<int> units;

	for ( int i = 0; i < static_cast<int>(formula.size()); i ++ ) {
		std::vector<int> &clause = formula[i];
		bool satisfied = false;
		int out = 0;
		for ( int literal : clause ) {
			const int8_t assigned = result.rootValues[abs(literal)];
			if ( assigned == 0 ) {
				clause[out ++] = literal;
			} else if ( assigned == (literal > 0 ? 1 : -1) ) {
				satisfied = true;
				break;
			}
		}
		if ( satisfied ) {
			alive[i] = 0;
			continue;
		}
		clause.resize(out);
		if ( clause.empty() ) return 20;
		if ( clause.size() == 1 ) units.push_back(clause[0]);
	}
	compactFormula(formula, alive);

	std::vector<std::vector<int>> occurrences(
		static_cast<size_t>(variableCount + 1) * 2
	);
	for ( int i = 0; i < static_cast<int>(formula.size()); i ++ ) {
		for ( int literal : formula[i] ) {
			occurrences[literalIndex(literal)].push_back(i);
		}
	}

	alive.assign(formula.size(), 1);
	while ( !units.empty() ) {
		const int literal = units.front();
		units.pop_front();
		const int variable = abs(literal);
		const int8_t assigned = literal > 0 ? 1 : -1;

		if ( result.rootValues[variable] != 0 ) {
			if ( result.rootValues[variable] != assigned ) return 20;
			continue;
		}
		result.rootValues[variable] = assigned;
		result.propagatedUnits ++;

		const std::vector<int> &satisfiedOccurrences =
			occurrences[literalIndex(literal)];
		for ( int clauseIndex : satisfiedOccurrences ) {
			if ( clauseIndex < static_cast<int>(alive.size()) ) {
				alive[clauseIndex] = 0;
			}
		}

		const int falseLiteral = -literal;
		const std::vector<int> &falseOccurrences =
			occurrences[literalIndex(falseLiteral)];
		for ( int clauseIndex : falseOccurrences ) {
			if ( clauseIndex >= static_cast<int>(alive.size()) ||
			     !alive[clauseIndex] ) continue;

			std::vector<int> &clause = formula[clauseIndex];
			auto position = std::lower_bound(
				clause.begin(),
				clause.end(),
				falseLiteral,
				ClauseOrder::literalLess
			);
			if ( position == clause.end() || *position != falseLiteral ) continue;
			clause.erase(position);
			if ( clause.empty() ) return 20;
			if ( clause.size() == 1 ) units.push_back(clause[0]);
		}
	}

	compactFormula(formula, alive);
	return 0;
}

// Test whether every source literal, except one optional literal, is in target
static bool isSubsetExcept( const std::vector<int> &source,
			    const std::vector<int> &target,
			    int skippedLiteral ) {
	for ( int literal : source ) {
		if ( literal == skippedLiteral ) continue;
		if ( !containsLiteral(target, literal) ) return false;
	}
	return true;
}

// Apply bounded backward subsumption and self-subsuming resolution
static int subsumeAndStrengthen( int variableCount,
				std::vector<std::vector<int>> &formula,
				PreprocessResult &result ) {
	std::vector<std::vector<int>> occurrences(
		static_cast<size_t>(variableCount + 1) * 2
	);
	for ( int i = 0; i < static_cast<int>(formula.size()); i ++ ) {
		for ( int literal : formula[i] ) {
			occurrences[literalIndex(literal)].push_back(i);
		}
	}

	std::vector<unsigned char> alive(formula.size(), 1);
	long long checks = 0;
	for ( int sourceIndex = 0;
	      sourceIndex < static_cast<int>(formula.size()) &&
	      checks < PREPROCESS_MAX_SUBSUMPTION_CHECKS;
	      sourceIndex ++ ) {
		if ( !alive[sourceIndex] ) continue;
		const std::vector<int> &source = formula[sourceIndex];
		if ( source.size() > PREPROCESS_MAX_SOURCE_CLAUSE ) continue;

		int rareLiteral = source[0];
		for ( int literal : source ) {
			if ( occurrences[literalIndex(literal)].size() <
			     occurrences[literalIndex(rareLiteral)].size() ) {
				rareLiteral = literal;
			}
		}

		const std::vector<int> subsumptionCandidates =
			occurrences[literalIndex(rareLiteral)];
		for ( int targetIndex : subsumptionCandidates ) {
			if ( checks ++ >= PREPROCESS_MAX_SUBSUMPTION_CHECKS ) break;
			if ( targetIndex == sourceIndex || !alive[targetIndex] ) continue;
			const std::vector<int> &target = formula[targetIndex];
			if ( target.size() < source.size() ||
			     target.size() > PREPROCESS_MAX_TARGET_CLAUSE ) continue;
			if ( target.size() == source.size() && sourceIndex > targetIndex ) continue;
			if ( isSubsetExcept(source, target, 0) ) {
				alive[targetIndex] = 0;
				result.subsumedClauses ++;
			}
		}

		for ( int pivot : source ) {
			const std::vector<int> strengtheningCandidates =
				occurrences[literalIndex(-pivot)];
			for ( int targetIndex : strengtheningCandidates ) {
				if ( checks ++ >= PREPROCESS_MAX_SUBSUMPTION_CHECKS ) break;
				if ( targetIndex == sourceIndex || !alive[targetIndex] ) continue;
				std::vector<int> &target = formula[targetIndex];
				if ( target.size() > PREPROCESS_MAX_TARGET_CLAUSE ||
				     source.size() > target.size() + 1 ) continue;
				if ( !containsLiteral(target, -pivot) ) continue;
				if ( !isSubsetExcept(source, target, pivot) ) continue;

				auto position = std::lower_bound(
					target.begin(),
					target.end(),
					-pivot,
					ClauseOrder::literalLess
				);
				if ( position != target.end() && *position == -pivot ) {
					target.erase(position);
					result.strengthenedClauses ++;
					if ( target.empty() ) return 20;
				}
			}
			if ( checks >= PREPROCESS_MAX_SUBSUMPTION_CHECKS ) break;
		}
	}

	compactFormula(formula, alive);
	return 0;
}

// Resolve two clauses on one variable
static int resolveClauses( const std::vector<int> &positive,
			   const std::vector<int> &negative,
			   int variable,
			   std::vector<int> &resolvent ) {
	resolvent.clear();
	int left = 0;
	int right = 0;
	while ( left < static_cast<int>(positive.size()) ||
		right < static_cast<int>(negative.size()) ) {
		while ( left < static_cast<int>(positive.size()) &&
			abs(positive[left]) == variable ) left ++;
		while ( right < static_cast<int>(negative.size()) &&
			abs(negative[right]) == variable ) right ++;

		if ( left == static_cast<int>(positive.size()) &&
		     right == static_cast<int>(negative.size()) ) break;
		if ( left == static_cast<int>(positive.size()) ) {
			resolvent.push_back(negative[right ++]);
			continue;
		}
		if ( right == static_cast<int>(negative.size()) ) {
			resolvent.push_back(positive[left ++]);
			continue;
		}

		const int leftLiteral = positive[left];
		const int rightLiteral = negative[right];
		if ( leftLiteral == rightLiteral ) {
			resolvent.push_back(leftLiteral);
			left ++;
			right ++;
		} else if ( abs(leftLiteral) == abs(rightLiteral) ) {
			return 1;
		} else if ( ClauseOrder::literalLess(leftLiteral, rightLiteral) ) {
			resolvent.push_back(leftLiteral);
			left ++;
		} else {
			resolvent.push_back(rightLiteral);
			right ++;
		}
	}
	return resolvent.empty() ? 20 : 0;
}

// Apply one bounded variable-elimination sweep
static int eliminateVariables( int variableCount,
			       std::vector<std::vector<int>> &formula,
			       PreprocessResult &result ) {
	std::vector<std::vector<int>> occurrences(
		static_cast<size_t>(variableCount + 1) * 2
	);
	std::vector<unsigned char> alive(formula.size(), 1);
	for ( int i = 0; i < static_cast<int>(formula.size()); i ++ ) {
		for ( int literal : formula[i] ) {
			occurrences[literalIndex(literal)].push_back(i);
		}
	}

	std::vector<int> order(variableCount);
	for ( int i = 0; i < variableCount; i ++ ) order[i] = i + 1;
	std::sort(order.begin(), order.end(), [&]( int left, int right ) {
		const size_t leftPositive = occurrences[literalIndex(left)].size();
		const size_t leftNegative = occurrences[literalIndex(-left)].size();
		const size_t rightPositive = occurrences[literalIndex(right)].size();
		const size_t rightNegative = occurrences[literalIndex(-right)].size();
		const size_t leftCost = leftPositive * leftNegative;
		const size_t rightCost = rightPositive * rightNegative;
		if ( leftCost != rightCost ) return leftCost < rightCost;
		return left < right;
	});

	std::vector<int> positiveClauses;
	std::vector<int> negativeClauses;
	std::vector<int> resolvent;
	for ( int variable : order ) {
		if ( result.rootValues[variable] != 0 || result.eliminated[variable] ) continue;

		positiveClauses.clear();
		negativeClauses.clear();
		for ( int clauseIndex : occurrences[literalIndex(variable)] ) {
			if ( clauseIndex < static_cast<int>(alive.size()) &&
			     alive[clauseIndex] &&
			     containsLiteral(formula[clauseIndex], variable) ) {
				positiveClauses.push_back(clauseIndex);
			}
		}
		for ( int clauseIndex : occurrences[literalIndex(-variable)] ) {
			if ( clauseIndex < static_cast<int>(alive.size()) &&
			     alive[clauseIndex] &&
			     containsLiteral(formula[clauseIndex], -variable) ) {
				negativeClauses.push_back(clauseIndex);
			}
		}

		if ( positiveClauses.empty() && negativeClauses.empty() ) {
			result.rootValues[variable] = 1;
			result.eliminated[variable] = 1;
			continue;
		}

		std::set<std::vector<int>, ClauseOrder> uniqueResolvents;
		if ( !positiveClauses.empty() && !negativeClauses.empty() ) {
			const size_t smaller = std::min(
				positiveClauses.size(),
				negativeClauses.size()
			);
			const size_t pairs = positiveClauses.size() * negativeClauses.size();
			if ( smaller > PREPROCESS_MAX_BVE_OCCURRENCE ||
			     pairs > PREPROCESS_MAX_BVE_PAIRS ) continue;

			bool bounded = true;
			for ( int positiveIndex : positiveClauses ) {
				for ( int negativeIndex : negativeClauses ) {
					const int status = resolveClauses(
						formula[positiveIndex],
						formula[negativeIndex],
						variable,
						resolvent
					);
					if ( status == 20 ) return 20;
					if ( status == 1 ) continue;
					if ( resolvent.size() > PREPROCESS_MAX_RESOLVENT_LENGTH ) {
						bounded = false;
						break;
					}
					uniqueResolvents.insert(resolvent);
					if ( uniqueResolvents.size() >
					     positiveClauses.size() + negativeClauses.size() ) {
						bounded = false;
						break;
					}
				}
				if ( !bounded ) break;
			}
			if ( !bounded ) continue;
		}

		EliminatedVariable record;
		record.variable = variable;
		record.clauses.reserve(positiveClauses.size() + negativeClauses.size());
		for ( int clauseIndex : positiveClauses ) {
			record.clauses.push_back(std::move(formula[clauseIndex]));
			alive[clauseIndex] = 0;
		}
		for ( int clauseIndex : negativeClauses ) {
			record.clauses.push_back(std::move(formula[clauseIndex]));
			alive[clauseIndex] = 0;
		}

		for ( const std::vector<int> &newClause : uniqueResolvents ) {
			const int clauseIndex = static_cast<int>(formula.size());
			formula.push_back(newClause);
			alive.push_back(1);
			for ( int literal : newClause ) {
				occurrences[literalIndex(literal)].push_back(clauseIndex);
			}
		}

		if ( !positiveClauses.empty() && negativeClauses.empty() ) {
			result.rootValues[variable] = 1;
		} else if ( positiveClauses.empty() && !negativeClauses.empty() ) {
			result.rootValues[variable] = -1;
		} else {
			result.rootValues[variable] = 1;
		}
		result.eliminated[variable] = 1;
		result.eliminationStack.push_back(std::move(record));
		result.eliminatedVariables ++;
		result.generatedResolvents += static_cast<long long>(uniqueResolvents.size());
	}

	compactFormula(formula, alive);
	return 0;
}

// Run the initial lightweight preprocessing pipeline
int preprocessFormula( int variableCount,
			std::vector<std::vector<int>> &formula,
			PreprocessResult &result ) {
	result.rootValues.assign(variableCount + 1, 0);
	result.eliminated.assign(variableCount + 1, 0);
	result.eliminationStack.clear();
	result.removedTautologies = 0;
	result.removedDuplicateLiterals = 0;
	result.propagatedUnits = 0;
	result.subsumedClauses = 0;
	result.strengthenedClauses = 0;
	result.eliminatedVariables = 0;
	result.generatedResolvents = 0;
	result.finalClauses = 0;
	result.finalLiterals = 0;

	const size_t occurrenceHeaders =
		static_cast<size_t>(variableCount + 1) * 2 *
		sizeof(std::vector<int>);
	const size_t formulaHeaders =
		formula.capacity() * sizeof(std::vector<int>);
	if ( occurrenceHeaders > PREPROCESS_MAX_AUXILIARY_BYTES ||
	     formulaHeaders > PREPROCESS_MAX_AUXILIARY_BYTES -
		occurrenceHeaders ) {
		fprintf( stderr, "preprocessing skipped for large formula\n" );
		result.finalClauses = static_cast<long long>(formula.size());
		for ( const std::vector<int> &clause : formula ) {
			result.finalLiterals += static_cast<long long>(clause.size());
		}
		return 0;
	}

	int out = 0;
	for ( int i = 0; i < static_cast<int>(formula.size()); i ++ ) {
		const int status = normalizeClause(variableCount, formula[i], result);
		if ( status == 30 || status == 20 ) return status;
		if ( status == 1 ) continue;
		if ( out != i ) formula[out] = std::move(formula[i]);
		out ++;
	}
	formula.resize(out);

	int status = propagateUnits(variableCount, formula, result);
	if ( status != 0 ) return status;

	for ( int pass = 0; pass < 2; pass ++ ) {
		status = subsumeAndStrengthen(variableCount, formula, result);
		if ( status != 0 ) return status;
		status = propagateUnits(variableCount, formula, result);
		if ( status != 0 ) return status;
	}

	status = eliminateVariables(variableCount, formula, result);
	if ( status != 0 ) return status;
	status = propagateUnits(variableCount, formula, result);
	if ( status != 0 ) return status;
	status = subsumeAndStrengthen(variableCount, formula, result);
	if ( status != 0 ) return status;
	status = propagateUnits(variableCount, formula, result);
	if ( status != 0 ) return status;

	result.finalClauses = static_cast<long long>(formula.size());
	for ( const std::vector<int> &clause : formula ) {
		result.finalLiterals += static_cast<long long>(clause.size());
	}
	return 0;
}

// Reconstruct eliminated variables in reverse elimination order
bool reconstructPreprocessedModel( const PreprocessResult &result,
				   std::vector<int8_t> &model ) {
	if ( model.size() != result.rootValues.size() ) return false;

	for ( int variable = 1; variable < static_cast<int>(model.size()); variable ++ ) {
		if ( result.rootValues[variable] != 0 &&
		     !result.eliminated[variable] ) {
			model[variable] = result.rootValues[variable];
		}
	}

	for ( int i = static_cast<int>(result.eliminationStack.size()) - 1;
	      i >= 0;
	      i -- ) {
		const EliminatedVariable &record = result.eliminationStack[i];
		bool requiresTrue = false;
		bool requiresFalse = false;

		for ( const std::vector<int> &clause : record.clauses ) {
			bool otherSatisfied = false;
			bool containsPositive = false;
			bool containsNegative = false;
			for ( int literal : clause ) {
				const int variable = abs(literal);
				if ( variable == record.variable ) {
					if ( literal > 0 ) containsPositive = true;
					else containsNegative = true;
					continue;
				}
				if ( model[variable] == (literal > 0 ? 1 : -1) ) {
					otherSatisfied = true;
					break;
				}
			}
			if ( otherSatisfied ) continue;
			if ( containsPositive ) requiresTrue = true;
			if ( containsNegative ) requiresFalse = true;
		}

		if ( requiresTrue && requiresFalse ) return false;
		if ( requiresTrue ) model[record.variable] = 1;
		else if ( requiresFalse ) model[record.variable] = -1;
		else model[record.variable] = result.rootValues[record.variable] != 0
			? result.rootValues[record.variable] : 1;
	}

	for ( int variable = 1; variable < static_cast<int>(model.size()); variable ++ ) {
		if ( model[variable] == 0 ) model[variable] = 1;
	}
	return true;
}
