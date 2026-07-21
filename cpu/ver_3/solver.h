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

    	bool empty() const { return heap.size() == 0; }

    	bool inHeap( int n ) const { return n < (int)pos.size() && pos[n] >= 0; }
    	
	void update( int x ) { up(pos[x]); }

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
    	// Literals in a clause
	std::vector<int> literals;
	// Overloading array operator
	// Return a certain literal in a clause
    	int& operator [] ( int index ) { return literals[index]; }
	// Initialize clause metadata and resize literal array
    	Clause( int sz ): lbd(0), activity(0.0), useCount(0) { literals.resize(sz); }
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
    	std::vector<WL> *watched_literals;              // A mapping from literal to clauses
    	
	int vars, clauses, origin_clauses, conflicts;   // The number of variables, clauses, and conflicts
	int decides, unitPropagations;                   // The number of decisions and unit propagations
	int bcpFunctionCalls;                            // The number of BCP function calls
    	int lbdResets, rephases, reduces;                // Parameters for LBD reset, soft rephase, and reduce
    	int rephase_inc, rephase_limit, reduce_limit;   // Parameters for rephase and reduce
    	int reductionRuns;
	long long deletedClauses, minimizedLiterals;
	long long clauseActivityBumps, dynamicLBDUpdates;
    	int threshold;                                  // A threshold for updating the local_best phase
    	int propagated;                                 // The number of propagated literals in trail
    	int time_stamp;                                 // Parameter for conflict analysis and LBD calculation
   
    	int lbd_queue[50],                              // Circled queue saved the recent 50 LBDs
            lbd_queue_size,                             // The number of LBDs in this queue
            lbd_queue_pos;                              // The position to save the next LBD
    	double fast_lbd_sum, slow_lbd_sum;              // Sum of the global and recent 50 LBDs

    	int8_t *value,                                  // The variable assignment (1:True; -1:False; 0:Undefined)
	       *local_best,                               // A phase with a local deepest trail
	       *saved;                                   // Phase saving
        int *reason,                                    // The index of the clause that implies the variable assignment
            *level,                                     // The decision level of a variable
            *mark;                                      // Parameter for conflict analysis
	unsigned int *lbdMark;                          // Decision-level marks for dynamic LBD
	unsigned int lbdStamp;

    	double *activity;                              // The variables' score for VSIDS
	double var_inc, var_decay;                       // Parameter for VSIDS
	double clause_inc, clause_decay;                 // Parameters for learnt-clause activity
    	Heap vsids;                                    // Heap to select variable

	double processTimeFinal;                         // Total elapsed time
	double propagaTimeFinal;                         // Propagation elapsed time
	double maxBCPTime;                               // Maximum elapsed time of BCP
	
	void initialize();                                        // Allocate memory and initialize the values
    	void assign( int literal, int level, int cref );          // Assign true value to a certain literal
	int  add_clause( std::vector<int> &c );                   // Add new clause to clause database
	int  propagate();                                         // BCP (Boolean Constraint Propagation)
    	int  parse( char *filename );                             // Read CNF file
	int  decide();                                            // Pick decision variable based on VSIDS
	void update_score( int var, double coeff );               // Update variable activity
	void bumpClauseActivity( int cref );                       // Update learnt-clause activity
	int  calculateClauseLBD( const Clause &clause );           // Calculate current LBD
	void updateClauseQuality( int cref );                      // Update usage activity and dynamic LBD
    	int  analyze( int cref, int &backtrack_level, int &lbd ); // Conflict analysis
	void backtrack( int backtrack_level );                    // Backtracking
    	void resetRecentLBD();                                  // Reset recent LBD statistics without backtracking
    	void rephase();                                         // Do rephase
    	void reduce();                                          // Do reduce
	int  solve();                                             // Solver
    	void printModel();                                      // Print model when the result is SAT
};


// Etc
// Additional funcs for reading CNF file
uint8_t *read_whitespace( uint8_t *p );
uint8_t *read_until_new_line( uint8_t *p );
uint8_t *read_int( uint8_t *p, int *i );
