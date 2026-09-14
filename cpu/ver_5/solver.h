#include <sys/resource.h>
#include <stdio.h>
#include <stdint.h>
#include <limits.h>
#include <stdlib.h>
#include <stdbool.h>
#include <vector>

struct EliminationRecord {
	int variable;
	int defaultValue;
	size_t offset;
	size_t end;
};


#define ChildLeft(x) (x << 1 | 1)
#define ChildRight(x) ((x + 1) << 1)
#define Parent(x) ((x - 1) >> 1)

#define Value(literal) (literal > 0 ? value[literal] : -value[-literal])
#define WatchedLiterals(id) (watched_literals[vars + id])


// Heap data structure (max heap)
class Heap {
	const double *activity = nullptr; // Pointer to activity database
	std::vector<int> heap; // Index of activity[x]
	std::vector<int> pos; // Actual position of heap

	bool compare( int a, int b ) const {
		return activity[a] > activity[b];
	}

	void up( int v ) {
		int x = heap[v];
		int p = Parent(v);

		// Child > Parent -> True
		while ( v && compare(x, heap[p]) ) {
			heap[v] = heap[p];
			pos[heap[p]] = v;
			v = p;
			p = Parent(p);
		}
		heap[v] = x;
		pos[x] = v;
	}

	void down( int v ) {
		int x = heap[v];
		while ( v < (int)heap.size() / 2 ) {
			// Pick the bigger one among left and right child
			int child = (ChildRight(v) < (int)heap.size()) &&
				compare(heap[ChildRight(v)], heap[ChildLeft(v)]) ?
				ChildRight(v) : ChildLeft(v);
			if ( compare(x, heap[child]) ) break;
			else {
				heap[v] = heap[child];
				pos[heap[v]] = v;
				v = child;
			}
		}
		heap[v] = x;
		pos[x] = v;
	}

public:
	void initialize( const double *s, int variables ) {
		activity = s;
		heap.clear();
		heap.reserve(static_cast<size_t>(variables));
		pos.assign(static_cast<size_t>(variables) + 1, -1);
	}

	bool empty( void ) const {
		return heap.size() == 0;
	}

	bool inHeap( int n ) const {
		return n < (int)pos.size() && pos[n] >= 0;
	}

	void update( int x ) {
		up(pos[x]);
	}

	void insert( int x ) {
		if ( (int)pos.size() < x + 1 ) pos.resize(x + 1, -1);
		pos[x] = heap.size();
		heap.push_back(x);
		up(pos[x]);
	}

	int pop( void ) {
		int x = heap[0];
		heap[0] = heap.back();
		pos[heap[0]] = 0;
		pos[x] = -1;
		heap.pop_back();
		if ( heap.size() > 1 ) down(0);
		return x;
	}
};


// Clause data
struct Clause {
	// Literal block distance based on Glucose
	// LBD = How many decision levels are represented in a learnt clause
	int lbd;
	// Usage-aware learnt-clause activity
	double activity;
	// The number of conflict-analysis uses
	uint32_t useCount;
	bool learntClause;
	bool permanent;
	bool removable;
	bool simplified;
	bool removed;
	// Literals in a clause
	std::vector<int> literals;

	// Return a certain literal in a clause
	int &operator [] ( int index ) {
		return literals[index];
	}

	// Initialize clause metadata and resize literal array
	Clause( int sz )
		: lbd(0), activity(0.0), useCount(0), learntClause(false), permanent(false),
		  removable(true), simplified(false), removed(false) {
		literals.resize(sz);
	}
};


// Watcher data
struct WL {
	// Which clause a watched literal is included
	int clauseIdx;
	// A flag for check whether a clause is already satisfied or not
	int blocker;

	WL( void )
		: clauseIdx(0), blocker(0) {
	}

	WL( int c, int b )
		: clauseIdx(c), blocker(b) {
	}
};


// Solver state and operations
struct Solver {
	Solver() = default;
	~Solver();
	Solver( const Solver & ) = delete;
	Solver &operator = ( const Solver & ) = delete;

	// Clause and assignment state
	std::vector<int> learnt;
	std::vector<int> trail;
	std::vector<int> decVarInTrail;
	std::vector<int> reduceMap;
	std::vector<Clause> clauseDB;
	std::vector<WL> *watched_literals = nullptr;

	int vars = 0;
	int clauses = 0;
	int origin_clauses = 0;

	// Search statistics and policies
	uint64_t conflicts = 0;
	uint64_t decides = 0;
	uint64_t unitPropagations = 0;
	uint64_t bcpFunctionCalls = 0;
	uint64_t restarts = 0;
	uint64_t reduces = 0;
	uint64_t firstReduceDB = 2000;
	uint64_t nbclausesbeforereduce = 2000;
	uint64_t curRestart = 1;
	uint64_t incReduceDB = 300;
	uint64_t specialIncReduceDB = 1000;
	uint64_t conflictsRestarts = 0;
	uint64_t noDecisionConflict = 0;
	uint64_t learntGlue = 0;
	uint64_t learntBinary = 0;
	uint64_t blockedRestarts = 0;
	size_t ordinaryLearntCount = 0;
	bool chanseokStrategy = false;
	bool glureduce = true;
	bool lubyRestart = false;
	bool randomizeOnRestarts = false;
	bool newDescent = false;
	bool adaptStrategies = true;
	bool performLCM = true;
	bool preprocessingDone = false;
	int coLBDBound = 5;
	uint32_t randomDescentAssignments = 0;
	double randomSeed = 91648253;

	// Restart and simplification state
	int trail_queue[5000];
	int trail_queue_size = 0;
	int trail_queue_pos = 0;
	uint64_t trailQueueSum = 0;
	int simpDBAssigns = -1;
	int64_t simpDBProps = 0;
	std::vector<int> analyzeStack;
	std::vector<int> analyzeToClear;
	std::vector<int> lastDecisionLevel;

	// Preprocessing and LCM state
	std::vector<uint8_t> eliminated;
	std::vector<EliminationRecord> eliminationRecords;
	std::vector<int> eliminationLiterals;
	uint64_t preprocessingEliminated = 0;
	uint64_t preprocessingSubsumed = 0;
	uint64_t preprocessingStrengthened = 0;
	uint64_t preprocessingResolvents = 0;
	uint64_t lcmRuns = 0;
	uint64_t lcmTested = 0;
	uint64_t lcmReduced = 0;
	uint64_t lcmLiteralsRemoved = 0;
	double preprocessTimeFinal = 0.0;
	double cpuDeadline = 0.0;

	// Solver counters
	uint64_t reductionRuns = 0;
	uint64_t deletedClauses = 0;
	uint64_t minimizedLiterals = 0;
	uint64_t clauseActivityBumps = 0;
	uint64_t dynamicLBDUpdates = 0;
	int propagated;
	uint32_t time_stamp;

	// LBD restart queues
	int lbd_queue[50];
	int lbd_queue_size;
	int lbd_queue_pos;
	double fast_lbd_sum;
	double slow_lbd_sum;

	// Variable state
	int8_t *value = nullptr;
	int8_t *forceUNSAT = nullptr;
	int8_t *saved = nullptr;
	int *reason = nullptr;
	int *level = nullptr;
	uint32_t *mark = nullptr;
	unsigned int *lbdMark = nullptr;
	unsigned int lbdStamp;
	double *activity = nullptr;
	double max_var_decay = 0.95;
	double var_inc;
	double var_decay;
	double clause_inc;
	double clause_decay;
	Heap vsids;

	// Timing results
	double processTimeFinal;
	double propagaTimeFinal;
	double maxBCPTime;

	// Solver operations
	void nextAnalysisStamp();
	void initialize();
	void assign( int literal, int level, int cref );
	int add_clause( std::vector<int> &c );
	int propagate();
	int parse( char *filename );
	int decide();
	void update_score( int var, double coeff );
	void bumpClauseActivity( int cref );
	int calculateLBD( const std::vector<int> &literals );
	int calculateClauseLBD( const Clause &clause );
	void updateClauseQuality( int cref );
	int analyze( int cref, int &backtrack_level, int &lbd );
	void backtrack( int backtrack_level );
	void restart();
	void reduce();
	bool withinBudget() const;
	void clearLBDQueue();
	void pushTrailSize();
	bool shouldRestart( uint64_t searchConflicts, uint64_t conflictBudget );
	void adaptSolver();
	static uint64_t luby( uint64_t index );
	bool literalRedundant( int literal, uint32_t abstractLevels );
	void binaryMinimization();
	void rebuildWatches();
	void compactClauses();
	bool simplifyRoot();
	int preprocess();
	bool extendModel();
	int vivifyLearnts();
	int solve();
	void printModel();

private:
	int parseStream( FILE *file );
};
