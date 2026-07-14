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
        	while ( ChildLeft(v) < (int)heap.size() ){
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
	// LBD = How many decision variable in a learnt clause
    	int lbd;
    	// Literals in a clause
	std::vector<int> literals;
	// Overloading array operator
	// Return a certain literal in a clause
    	int& operator [] ( int index ) { return literals[index]; }
	// Initialize literal block distance value as 0
	// Resize literal array size
    	Clause( int sz ): lbd(0) { literals.resize(sz); }
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
    	std::vector<int> learnt,			// The clause indices of the learnt clauses
                         trail,				// Save the assigned literal sequence
                         decVarInTrail,                 // Save the decision variables' position in trail
                         reduceMap;                     // Auxiliary data structure for clause management
    	std::vector<Clause> clauseDB;                   // Clause database
    	std::vector<WL> *watched_literals;              // A mapping from literal to clauses
    	
	int vars, clauses, origin_clauses, conflicts;   // The number of variables, clauses, and conflicts
	int decides, unitPropagations;			// The number of decides and unit propagations
	int bcpFunctionCalls;				// The number of BCP function calls
    	int restarts, rephases, reduces;                // Parameters for restart, rephase, and reduce
    	int rephase_inc, rephase_limit, reduce_limit;   // Parameters for rephase and reduce
    	int threshold;                                  // A threshold for updating the local_best phase
    	int propagated;                                 // The number of propagted literals in trail
    	int time_stamp;                                 // Parameter for conflict analyzation and LBD calculation
   
    	int lbd_queue[50],                              // Circled queue saved the recent 50 LBDs
            lbd_queue_size,                             // The number of LBDs in this queue
            lbd_queue_pos;                              // The position to save the next LBD
    	double fast_lbd_sum, slow_lbd_sum;		// Sum of the global and recent 50 LBDs

    	int8_t *value,					// The variable assignement (1:True; -1:False; 0:Undefine)
	       *local_best,				// A phase with a local deepest trail
	       *saved;					// Phase saving
        int *reason,                                    // The index of the clause that implies the variable assignment
            *level,                                     // The decision level of a variable      
            *mark;                                      // Parameter for conflict analyzation

    	double *activity;				// The variables' score for VSIDS
	double var_inc, var_decay;			// Parameter for VSIDS
    	Heap vsids;					// Heap to select variable

	double processTimeFinal;			// Total elapsed time
	double propagaTimeFinal;			// Propagation elapsed time
	double maxBCPTime;				// Maximum elapsed time of BCP
	
	void initialize();                                        // Allocate memory and initialize the values 
    	void assign( int literal, int level, int cref );          // Assign true value to a certain literal
	int  add_clause( std::vector<int> &c );                   // Add new clause to clause database
	int  propagate();                                         // BCP (Boolean Contraint Propagation)
    	int  parse( char *filename );                             // Read CNF file
	int  decide();                                            // Pick decision variable based on VSIDS
	void update_score( int var, double coeff );		  // Update activity
    	int  analyze( int cref, int &backtrack_level, int &lbd ); // Conflict analysis
	void backtrack( int backtrack_level );                    // Backtracking
    	void restart();                                           // Do restart
    	void rephase();                                           // Do rephase
    	void reduce();                                            // Do reduce
	int  solve();                                             // Solver
    	void printModel();                                        // Print model when the result is SAT
};


// Etc
// Additional funcs for reading CNF file
uint8_t *read_whitespace( uint8_t *p );
uint8_t *read_until_new_line( uint8_t *p );
uint8_t *read_int( uint8_t *p, int *i );
