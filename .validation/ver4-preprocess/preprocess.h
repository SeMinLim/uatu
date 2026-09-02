#ifndef UATU_VER4_PREPROCESS_H
#define UATU_VER4_PREPROCESS_H

#include <stdint.h>
#include <vector>


typedef struct EliminatedVariable {
	int variable;
	std::vector<std::vector<int>> clauses;
}EliminatedVariable;

typedef struct PreprocessResult {
	std::vector<int8_t> rootValues;
	std::vector<unsigned char> eliminated;
	std::vector<EliminatedVariable> eliminationStack;
	long long removedTautologies;
	long long removedDuplicateLiterals;
	long long propagatedUnits;
	long long subsumedClauses;
	long long strengthenedClauses;
	long long eliminatedVariables;
	long long generatedResolvents;
	long long finalClauses;
	long long finalLiterals;
}PreprocessResult;


int preprocessFormula( int variableCount,
			std::vector<std::vector<int>> &formula,
			PreprocessResult &result );
bool reconstructPreprocessedModel( const PreprocessResult &result,
				   std::vector<int8_t> &model );

#endif
