#ifndef UATU_VER4_SOLVER_H
#define UATU_VER4_SOLVER_H

#include "preprocess.h"
#include <sys/resource.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdbool.h>
#include <vector>


#define ChildLeft(x) (x << 1 | 1)
#define ChildRight(x) ((x + 1) << 1)
#define Parent(x) ((x - 1) >> 1)

#define Value(literal) (literal > 0 ? value[literal] : -value[-literal])
#define WatchedLiterals(id) (watched_literals[vars + id])


// Heap data structure (max heap)
class Heap {
    	const double *activity; // Pointer to activity database
    	std::vector<int> heap; // Index of activity[x]
    	std::vector<int> pos; // Actual position of heap

	bool compare( int a, int b ) const { return activity[a] > activity[b]; }

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
        	while ( ChildLeft(v) < (int)heap.size() ) {
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
    	void initialize( const double *s ) {
		activity = s;
	}

	void rebuild( const double *s, int variableCount ) {
		activity = s;
		heap.clear();
		pos.assign(variableCount + 1, -1);
		heap.reserve(variableCount);
		for ( int variable = 1; variable <= variableCount; variable ++ ) {
			insert(variable);
		}
	}

    	bool empty() const { return heap.size() == 0; }
	int top() const { return heap[0]; }

    	bool inHeap( int n ) const { return n < (int)pos.size() && pos[n] >= 0; }
    	
	void update( int x ) {
		if ( !inHeap(x) ) return;
		up(pos[x]);
		down(pos[x]);
	}

    	void insert( int x ) {
        	if ( (int)pos.size() < x + 1 ) pos.resize(x + 1, -1);	
		pos[x] = heap.size();
        	heap.push_back(x);
        	up(pos[x]); 
    	}

    	int pop() {
        	int x = heap[0];
        	heap[0] = heap.back();
        	pos[heap[0]] = 0;
		pos[x] = -1;
        	heap.pop_back();
        	if ( heap.size() > 1 ) down(0);
        	return x; 
    	}
};


// Clause
class Clause {
public:
	// Literal block distance based on Glucose
	// LBD = How many decision levels are represented in a learnt clause
    	int lbd;
	// Usage-aware learnt-clause activity
	double activity;
	// The number of conflict-analysis uses
	uint32_t useCount;
	// Whether this clause has already been checked by vivification
	bool vivified;
    	// Literals in a clause
	std::vector<int> literals;
	// Overloading array operator
	// Return a certain literal in a clause
    	int& operator [] ( int index ) { return literals[index]; }
	// Initialize clause metadata and resize literal array
    	Clause( int sz ): lbd(0), activity(0.0), useCount(0), vivified(false) { literals.resize(sz); }
};


// Watcher list
class WL {
public:
	// Which clause a watched literal is included
	// A index of a clause in ClauseDB
    	int clauseIdx;
	// A flag for check whether a clause is already satisfied or not
    	int blocker;
    	WL(): clauseIdx(0), blocker(0) {}
    	WL( int c, int b ): clauseIdx(c), blocker(b) {}
};


// Solver
class Solver {
public:
    	std::vector<int> learnt,                         // The literals of the learnt clause
                         trail,                         // Save the assigned literal sequence
                         decVarInTrail,                 // Save the decision variables' position in trail
                         reduceMap;                     // Auxiliary data structure for clause management
    	std::vector<Clause> clauseDB;                   // Clause database
	PreprocessResult preprocessing;                // Initial preprocessing state
	std::vector<int8_t> model;                       // Reconstructed SAT model
	double preprocessingTime = 0.0;                 // Initial preprocessing elapsed time
    	std::vector<WL> *watched_literals = nullptr;    // A mapping from literal to clauses
    	
	int vars = 0, clauses = 0, origin_clauses = 0, conflicts = 0;   // The number of variables, clauses, and conflicts
	int decides = 0, unitPropagations = 0;                   // The number of decisions and unit propagations
	int bcpFunctionCalls = 0;                            // The number of BCP function calls
    	int lbdResets = 0, rephases = 0, reduces = 0;                // Parameters for LBD reset, soft rephase, and reduce
    	int rephase_inc = 0, rephase_limit = 0, reduce_limit = 0;   // Parameters for rephase and reduce
    	int reductionRuns = 0, vivificationRuns = 0;
	long long deletedClauses = 0, minimizedLiterals = 0;
	long long clauseActivityBumps = 0, dynamicLBDUpdates = 0;
	long long vivificationCandidates = 0, vivifiedClauses = 0, vivifiedLiterals = 0;
	long long vivificationUnits = 0, vivificationBCPCalls = 0;
	long long vivificationPropagations = 0;
    	int threshold = 0;                                  // A threshold for updating the local_best phase
    	int propagated = 0;                                 // The number of propagated literals in trail
    	int time_stamp = 0;                                 // Parameter for conflict analysis and LBD calculation
   
    	int lbd_queue[50] = {0},                              // Circled queue saved the recent 50 LBDs
            lbd_queue_size = 0,                             // The number of LBDs in this queue
            lbd_queue_pos = 0;                              // The position to save the next LBD
    	double fast_lbd_sum = 0.0, slow_lbd_sum = 0.0;              // Sum of the global and recent 50 LBDs

    	int8_t *value = nullptr,                        // The variable assignment (1:True; -1:False; 0:Undefined)
	       *local_best = nullptr,                     // A phase with a local deepest trail
	       *saved = nullptr;                          // Phase saving
        int *reason = nullptr,                          // The index of the clause that implies the variable assignment
            *level = nullptr,                           // The decision level of a variable
            *mark = nullptr;                            // Parameter for conflict analysis
	unsigned int *lbdMark = nullptr;                // Decision-level marks for dynamic LBD
	unsigned int lbdStamp = 0;
	bool vivificationActive = false;

    	double *activity = nullptr;                    // The variables' score for EVSIDS
	double var_inc = 0.0, var_decay = 0.0;               // Parameters for EVSIDS
	double *lrbActivity = nullptr;                       // The variables' score for LRB
	uint32_t *lrbTimestamp = nullptr;                   // Assignment or cancellation conflict stamp
	uint32_t *lrbParticipated = nullptr;                // Conflict participation in one interval
	uint32_t *lrbReasoned = nullptr;                    // Reason-side participation in one interval
	double lrbStepSize = 0.0;                           // LRB moving-average step size
	double lrbStepSizeDecrease = 0.0;                   // LRB step-size decrement per conflict
	double lrbMinimumStepSize = 0.0;                    // Minimum LRB step size
	unsigned long long lrbConflictClock = 0;            // Conflict clock for LRB intervals
	unsigned long long branchingPropagations = 0;       // Search propagations for switching
	unsigned long long branchingPhaseBudget = 0;        // Current propagation budget per mode
	unsigned long long branchingNextSwitch = 0;         // Propagation count for next switch
	long long lrbDecisions = 0, evsidsDecisions = 0;    // Decisions by each heuristic
	long long lrbUpdates = 0;                           // Completed LRB interval updates
	int branchingSwitches = 0;                          // Number of mode switches
	bool useLRBBranching = true;                        // Active branching heuristic
	double clause_inc = 0.0, clause_decay = 0.0;       // Parameters for learnt-clause activity
    	Heap vsids;                                    // Shared variable-order heap

	double processTimeFinal = 0.0;                         // Total elapsed time
	double propagaTimeFinal = 0.0;                         // Propagation elapsed time
	double maxBCPTime = 0.0;                               // Maximum elapsed time of BCP

	~Solver() {
		delete [] value;
		delete [] local_best;
		delete [] saved;
		delete [] reason;
		delete [] level;
		delete [] mark;
		delete [] lbdMark;
		delete [] activity;
		delete [] lrbActivity;
		delete [] lrbTimestamp;
		delete [] lrbParticipated;
		delete [] lrbReasoned;
		delete [] watched_literals;
	}
	
	void initialize();                                        // Allocate memory and initialize the values
    	void assign( int literal, int level, int cref );          // Assign true value to a certain literal
	int  add_clause( std::vector<int> &c );                   // Add new clause to clause database
	int  add_clause( std::vector<int> &&c );                  // Move an input clause to clause database
	int  propagate();                                         // BCP (Boolean Constraint Propagation)
    	int  parse( char *filename );                             // Read CNF file
	int  decide();                                            // Pick decision variable by LRB or EVSIDS
	void initializeBranching();                                // Initialize LRB and switching state
	void recordLRBAssignment( int variable );                  // Begin one LRB learning interval
	void recordLRBConflict( const std::vector<int> &variables ); // Record one LRB conflict
	void updateLRBOnUnassign( int variable );                  // Finish one LRB learning interval
	void applyLRBLocalityDecay( int variable );                // Penalize stale variables
	void updateBranchingMode();                                // Switch by propagation budget
	void update_score( int var, double coeff );               // Update EVSIDS variable activity
	void bumpClauseActivity( int cref );                       // Update learnt-clause activity
	int  calculateClauseLBD( const Clause &clause );           // Calculate current LBD
	void updateClauseQuality( int cref );                      // Update usage activity and dynamic LBD
    	int  analyze( int cref, int &backtrack_level, int &lbd ); // Conflict analysis
	void backtrack( int backtrack_level );                    // Backtracking
    	void resetRecentLBD();                                  // Reset recent LBD statistics without backtracking
    	void rephase();                                         // Do rephase
	void detachClause( int cref );                             // Detach a clause from watch lists
	void attachClause( int cref );                             // Attach a clause to watch lists
	void restoreVivificationTrail( int trailSize );            // Restore root state after vivification
	int  vivifyReductionEpoch();                               // Vivify clauses at a reduction epoch
    	int  reduce();                                           // Do reduce and vivification
	int  solve();                                             // Solver
    	void printModel();                                      // Print model when the result is SAT
};


// Etc
// Additional funcs for reading CNF file
uint8_t *read_whitespace( uint8_t *p );
uint8_t *read_until_new_line( uint8_t *p );
uint8_t *read_int( uint8_t *p, int *i );

#endif
