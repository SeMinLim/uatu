#include "solver.h"


//// Required functions
// Elapsed time checker
static inline double timeCheckerCPU( void ) {
        struct rusage ru;
        getrusage(RUSAGE_SELF, &ru);
        
	return (double)ru.ru_utime.tv_sec + (double)ru.ru_utime.tv_usec / 1000000;
}

// Functions for reading CNF (Conjunctive Normal Form) file
uint8_t *read_whitespace( uint8_t *p ) {
        // ASCII
	// 9 : Horizontal tab, 	10: Line feed or new line
	// 11: Vertical tab,	12: Form feed or new page
	// 13: Carriage return	32: Space
        while ( (*p >= 9 && *p <= 13) || *p == 32 ) ++p;
        
	return p;
}
uint8_t *read_until_new_line( uint8_t *p ) {
        while ( *p != '\n' ) {
                if ( *p++ == '\0' ) exit(1);
        }
        
	return ++p;
}
uint8_t *read_int( uint8_t *p, int *i ) {
        bool sym = true;
        *i = 0;
        
	p = read_whitespace(p);
        
	if ( *p == '-' ) {
                sym = false;
                ++ p;
        }
        
	while ( *p >= '0' && *p <= '9' ) {
                if ( *p == '\0' ) {
			return p;
		} else {
			*i = *i * 10 + *p - '0';
			++ p;
		}
        }
        
	if ( !sym ) *i = -(*i);
        
	return p;
}


//// Solver
// Allocate memory and initialize the values
void Solver::initialize( void ) {
    	value  = new int8_t[vars + 1];
    	local_best = new int8_t[vars + 1];
	saved = new int8_t[vars + 1];
	reason = new int[vars + 1];
    	level = new int[vars + 1];
    	mark = new int[vars + 1];
    	activity = new double[vars + 1];
    	watched_literals = new std::vector<WL>[vars * 2 + 1]; 		// Two polarities
    	
	conflicts = decides = unitPropagations = bcpFunctionCalls = 0;
	restarts = rephases = reduces = 0;
    	threshold = propagated = time_stamp = 0;
	fast_lbd_sum = lbd_queue_size = lbd_queue_pos = slow_lbd_sum = 0;
	processTimeFinal = propagaTimeFinal = maxBCPTime = 0.00;

    	var_inc = 1;
	var_decay = 0.8;
	rephase_inc = 1e5, rephase_limit = 1e5, reduce_limit = 8192;	// Heuristic values

	vsids.initialize(activity);
    	for (int i = 1; i <= vars; i++) {
        	value[i] = reason[i] = level[i] = mark[i] = local_best[i] = activity[i] = saved[i] = 0;
		vsids.insert(i);
    	}
}

// Assign 'true' value to a certain literal
void Solver::assign( int literal, int l, int cref ) {
	// Only make the literal 'true'
	// Assign 'true' if a selected literal has positive value
	// Assign 'false' if a selected literal has negative value
	int var = abs(literal);
    	value[var]  = literal > 0 ? 1 : -1;
    	level[var]  = l;
	reason[var] = cref;                                         
    	trail.push_back(literal);
}

// Add a clause to the database
int Solver::add_clause( std::vector<int> &c ) {                   
    	clauseDB.push_back(Clause(c.size()));                          
    	
	int id = clauseDB.size() - 1;                                
    	for ( int i = 0; i < (int)c.size(); i++ ) clauseDB[id][i] = c[i];
        
	// Two watched literals
	// We only make the literals 'true'
	// Then our only concern is the opposite ones, -c[0] and -c[1]
	// c[0] is a blocker for c[1] and vice versa
    	WatchedLiterals(-c[0]).push_back(WL(id, c[1])); // watched_literals[vars-c[0]]                      
    	WatchedLiterals(-c[1]).push_back(WL(id, c[0])); // watched_literals[vars-c[1]]

    	return id;                                                      
}

// BCP (Boolean Constraint Propagation)
int Solver::propagate( void ) {
	double bcpStart = timeCheckerCPU();
	// This propagate style is fully based on MiniSAT
    	while ( propagated < (int)trail.size() ) { 
		// 'p' is already assigned as 'true'
		// We now are gonna only concern '-p'
        	int p = trail[propagated++];
        	
		// Take an array of '-p'
		std::vector<WL> &ws = WatchedLiterals(p);
		
		// Check all clauses that contains '-p'
		int num_clauses = ws.size();
		int j = 0;
		for ( int i = 0; i < num_clauses; ) {
			//// STEP 1
			// To make the BCP progess fast
			// Check whether a clause is already satisfied via blocker
			// If then, move to the next clause that also has '-p'
            		int blocker = ws[i].blocker;                       
			if ( Value(blocker) == 1 ) {                
                		ws[j++] = ws[i++];
				continue;
            		}
		
			// We only take care of the position c[0], c[1]
			// If c[0] is '-p',
			// move it to c[1] and bring c[1] to c[0],
			// to fill c[0] with a new watched literal
			int cref = ws[i].clauseIdx;
			Clause& c = clauseDB[cref];
			int falseLiteral = -p; 
            		if ( c[0] == falseLiteral ) {
				c[0] = c[1];
				c[1] = falseLiteral;
			}

			i ++;
			
			//// STEP 2
			int firstWP = c[0];
			WL w = WL(cref, firstWP);
			if ( Value(firstWP) == 1 ) {
				// If c[0] is already assigned as 'true', 
				// then clause is already satisfied
                		ws[j++] = w;
				continue;
            		} else {
				// If c[0] is 'false',
				// the we need to look for a new watched literal in this clause
				// Try to find an 'undefined' literal
				int k;
				int sz = c.literals.size();
            			for ( k = 2; (k < sz) && (Value(c[k]) == -1); k ++ ); 
				if ( k < sz ) {
					// There is an 'undefined' literal!
					// Bring the 'undefined' literal to c[1]
        	       	 		c[1] = c[k];
					c[k] = falseLiteral;
				
					// Make c[0] as blocker for c[1]
                			WatchedLiterals(-c[1]).push_back(w);
				} else { 
					// There is no 'undefined' literal!
					// then, clause is under unit propagation
					ws[j++] = w;
				
					// Check c[0]'s value
                			if ( Value(firstWP) == -1 ) {
						// Conflict!	
                    				while ( i < num_clauses ) ws[j++] = ws[i++];
				
						// Terminate BCP, resize the array of '-p', 
						// and go to backtracking step carrying with the index of clause
                    				ws.resize(j);
                    		
						return cref;
                			} else {
						// Not conflict!
						// It means c[0] is an 'undefined' literal
						// Assign!
						assign(firstWP, level[abs(p)], cref);
						
						// Parameter update
						unitPropagations ++;
					}
				}
            		}
		}

		// Resize the array of '-p'
        	ws.resize(j);
    	}
	
	// Parameter update
	bcpFunctionCalls ++;

	double bcpFinish = timeCheckerCPU();
	double bcpTime = bcpFinish - bcpStart;
	if ( bcpTime > maxBCPTime ) maxBCPTime = bcpTime;

    	return -1;                                       
}

// Read CNF file
int Solver::parse( char *filename ) {
    	FILE *f_data = fopen(filename, "r");  

	// Get the file size first
    	fseek(f_data, 0, SEEK_END);
    	size_t file_len = ftell(f_data);

	// Then read the file
	fseek(f_data, 0, SEEK_SET);
	uint8_t *data = new uint8_t[file_len + 1];
	uint8_t *p = data;
	fread(data, sizeof(uint8_t), file_len, f_data);
	fclose(f_data);                                             
	data[file_len] = '\0';

	// Save a clause temporarily to go to the database
    	std::vector<int> buffer;

	// Parse the file
	while ( *p != '\0' ) {
        	p = read_whitespace(p);
        	
		if ( *p == '\0' ) {
			break;
		} else {
        		if ( *p == 'c' ) {
				// If there are some comments in CNF file
				p = read_until_new_line(p);
			} else if ( *p == 'p' ) {
				// Get informations 
            			if ( (*(p + 1) == ' ') && (*(p + 2) == 'c') && 
				     (*(p + 3) == 'n') && (*(p + 4) == 'f') ) {
					p += 5; 
					p = read_int(p, &vars); 
					p = read_int(p, &clauses);
                			initialize();
            			} else {
					printf("PARSE ERROR(Unexpected Char)!\n");
					exit(2);
				}
        		} else {
				// Get literals
            			int32_t dimacs_lit;
            			p = read_int(p, &dimacs_lit);
            			if ( dimacs_lit != 0 ) { 
					if ( *p == '\0' ) {
        	       	 			printf("c PARSE ERROR(Unexpected EOF)!\n");
						exit(1);
					} else {
						buffer.push_back(dimacs_lit);
					}
				} else {                                                       
        	       	 		if ( buffer.size() == 0 ) {
						return 20;
					} else if ( buffer.size() == 1 ) {
						if ( Value(buffer[0]) == -1 ) return 20;
						else if ( !Value(buffer[0]) ) assign(buffer[0], 0, -1);
					} else add_clause(buffer); 

                			buffer.clear();                                        
            			}
        		}
    		}
	}

    	origin_clauses = clauseDB.size();
    	return ( propagate() == -1 ? 0 : 20 );             
}

// Pick decision variable based on VSIDS
int Solver::decide( void ) {
	// Pop VSIDS max-heap until finding an undefined literal
    	int next = -1;
	while ( next == -1 || Value(next) != 0 ) {
        	if ( vsids.empty() ) return 10;
        	else next = vsids.pop();
    	}
	
	// Save the decision variable's position in trail
    	decVarInTrail.push_back(trail.size());
    	
	// If there's saved one (polarity), use that
	if ( saved[next] ) next *= saved[next];

	// Assign
    	assign(next, decVarInTrail.size(), -1);

	// Parameter update
    	decides ++;

	return 0;
}

// Update activity
void Solver::update_score( int var, double coeff ) {
	// Update score and prevent overflow
	// Double type bumping scheme
	if ( (activity[var] += var_inc * coeff) > 1e100 ) {
		for ( int i = 1; i <= vars; i ++ ) activity[i] *= 1e-100;
		var_inc *= 1e-100;
	}
	
	// Update Heap
    	if ( vsids.inHeap(var) ) vsids.update(var);
}

// Conflict analysis
int Solver::analyze( int conflict, int &backtrackLevel, int &lbd ) {
	// This analysis is based on 'First UIP Learning Method' proposed by Chaff
	// UIP = Unit Implication Points
	// The main motivation for identifying UIPs is to reduce the size of learnt clauses
	// In the implication graph, 
	// there is a UIP at decision level d,
	// when the number of literals in intermediate clause
	// assigned at decision level d is 1
	
	// Parameter rearrangement
    	++ time_stamp;
    	learnt.clear();

	// Get the clause which is a reason for the conflict
    	Clause &c = clauseDB[conflict]; 
	int conflictLevel = level[abs(c[0])];

    	if ( conflictLevel == 0 ) {
		// UNSAT
		return 20;
	} else {
		// Reserve a room for saving the first UIP later
		learnt.push_back(0);

		// # of literals that have not visited
		// in the conflict level of the implication graph
		int should_visit = 0;
		
		// The literal to do resolution
		int resolve_lit = 0;
		int index = trail.size() - 1;

		// Store variables participated in arousing the conflict
		// to apply our own activity update heuristic
		std::vector<int> bump;

		// First UIP learning method
		do {
			// Get a clause related to the conflict
			Clause &c = clauseDB[conflict];

			// Mark the literals
			for ( int i = (resolve_lit == 0 ? 0 : 1); i < (int)c.literals.size(); i ++ ) {
				int var = abs(c[i]);
				if ( mark[var] != time_stamp && level[var] > 0 ) {
					// Update score (step 1)
					update_score(var, 0.5);
					bump.push_back(var);

					// Mark the literal to indicate it have visited
					mark[var] = time_stamp;

					// If the literal is contained in the upper level clause,
					// we don't need to check further,
					// following first UIP learning scheme
					if ( level[var] >= conflictLevel ) should_visit ++;
					else learnt.push_back(c[i]);
				}
			}
		
			// Find the last marked literal in the trail to do resolution
			while ( mark[abs(trail[index--])] != time_stamp );
			resolve_lit = trail[index + 1];
			
			// Get the index of clause that has the resolving-needed literal	
			conflict = reason[abs(resolve_lit)];

			// Parameter update
			mark[abs(resolve_lit)] = 0;
			should_visit --;
		} while ( should_visit > 0 );

		// Finalize composing a learnt clause
		learnt[0] = -resolve_lit;
		
		// Calculate LBD
		++ time_stamp;
		lbd = 0;
		for ( int i = 0; i < (int)learnt.size(); i++ ) {
			int l = level[abs(learnt[i])];
			if ( l && mark[l] != time_stamp ) {
				mark[l] = time_stamp;
				++ lbd;
			}
		}

		// Rearrange and update LBD queue
		if ( lbd_queue_size < 50 ) lbd_queue_size++;
		else fast_lbd_sum -= lbd_queue[lbd_queue_pos];
		lbd_queue[lbd_queue_pos++] = lbd;
		if ( lbd_queue_pos == 50 ) lbd_queue_pos = 0;

		// Sum of the recent 50 LBDs and global LBDs
		fast_lbd_sum += lbd;
		slow_lbd_sum += (lbd > 50 ? 50 : lbd);
			
		// Decide backtrack level
		if ( learnt.size() == 1 ) {
			backtrackLevel = 0;
		} else {
			int max_id = 1;
			for ( int i = 2; i < (int)learnt.size(); i ++ ) {
				if ( level[abs(learnt[i])] > level[abs(learnt[max_id])] ) max_id = i;
			}
			int p = learnt[max_id];
			learnt[max_id] = learnt[1];
			learnt[1] = p;
			backtrackLevel = level[abs(p)];
		}

		// Update score (step 2)
		// Our own activity update scheme
		// Update the activity of all literals
		// that affected the conflict and are located before the backtrack level
		for ( int i = 0; i < (int)bump.size(); i ++ ) {   
			if ( level[bump[i]] >= backtrackLevel - 1 ) update_score(bump[i], 1);
		}
	}

    	return 0;
}

// Backtracking
void Solver::backtrack( int backtrackLevel ) {
    	if ( (int)decVarInTrail.size() <= backtrackLevel ) {
		return;
	} else {
		for ( int i = trail.size() - 1; i >= decVarInTrail[backtrackLevel]; i -- ) {
			// Delete assignment
			int v = abs(trail[i]);
			value[v] = 0;

			// Phase saving
			saved[v] = trail[i] > 0 ? 1 : -1;
			
			// Store variable back to VSIDS heap
			if ( !vsids.inHeap(v) ) vsids.insert(v);
		}

		// Parameter and array update
		propagated = decVarInTrail[backtrackLevel];
		trail.resize(propagated);
		decVarInTrail.resize(backtrackLevel);
	}
}

// Restart
void Solver::restart() {	
	// Initialize recent 50 LBDs' sum and its queue
    	fast_lbd_sum = lbd_queue_size = lbd_queue_pos = 0;

	// Back to decision level
    	backtrack(decVarInTrail.size());

	// Update parameter
	restarts ++;
}

// Rephase
void Solver::rephase() {
	// This rephase style is fully based on CaDiCaL
	// Change the saved value to local best value
	// or flipped local best value
	if ( rephases/2 == 1 ) for ( int i = 1; i <= vars; i ++ ) saved[i] = local_best[i];
	else for ( int i = 1; i <= vars; i ++ ) saved[i] = -local_best[i];
	
	// Back to decision level
	backtrack(decVarInTrail.size());

	// Parameter update
	rephase_inc *= 2;
	rephase_limit = conflicts + rephase_inc;
	rephases ++;
}

// Clause deletion
void Solver::reduce() {
	// Go back to the first decision level first
    	backtrack(0);

    	reduces = 0;
	reduce_limit += 512;
    	
	int new_size = origin_clauses;
	int old_size = clauseDB.size();

	reduceMap.resize(old_size);
	
	// Randomly delete 50% bad clauses (LBD >= 5) 
    	for ( int i = origin_clauses; i < old_size; i ++ ) { 
        	if ( clauseDB[i].lbd >= 5 && rand() % 2 == 0 ) {
			reduceMap[i] = -1;
		} else {
			if ( new_size != i ) clauseDB[new_size] = clauseDB[i];
            		reduceMap[i] = new_size ++;
        	}
    	}

	// Resize the clause database
    	clauseDB.resize(new_size, Clause(0));
    	
	// Update the array of watched literals
	for ( int v = -vars; v <= vars; v ++ ) {
        	if ( v == 0 ) continue;

		// Get the array of a certain literal acting as watched literal
        	int old_sz = WatchedLiterals(v).size();
		int new_sz = 0;
        	for ( int i = 0; i < old_sz; i ++ ) {
            		int old_idx = WatchedLiterals(v)[i].clauseIdx;
            		int new_idx = old_idx < origin_clauses ? old_idx : reduceMap[old_idx];

			// For a not deleted clause, then the clause has a different index now
			// We need to its clause index and the position in the array
            		if ( new_idx != -1 ) {
                		WatchedLiterals(v)[i].clauseIdx = new_idx;
				if ( new_sz != i ) WatchedLiterals(v)[new_sz] = WatchedLiterals(v)[i];
                		new_sz ++;
            		}
        	}

		// Resize the array of watched literals
        	WatchedLiterals(v).resize(new_sz);
    	}
}

// Solver
int Solver::solve() {
    	int res = 0;
	double processStart = timeCheckerCPU();
    	
	while (!res) {
		double processFinish = timeCheckerCPU();
		double processTime = processFinish - processStart;

		if ( processTime < 2000 ) {
			//double propagaStart = timeCheckerCPU();
			int cref = propagate();
			//double propagaFinish = timeCheckerCPU();
			//propagaTimeFinal += propagaFinish - propagaStart;

		
			// Find a conflict
			if ( cref != -1 ) {
				int backtrackLevel = 0; 
				int lbd = 0;
				
				res = analyze(cref, backtrackLevel, lbd);
			
				if ( res == 20 ) {
					// Find a conflict in 0 decision level
					// UNSAT
					break;
				} else {
					backtrack(backtrackLevel);
				
					if ( learnt.size() == 1 ) {
						// Unit learnt clause
						// This means backtrack level must be 0 decision level
						// Because after first assignment,
						// the solver only assigned a value to originally unit clause
						// and the other literal containing the unit clause deleted
						// via resolution step
						// No need to add to clause database
						
						// Assign
						assign(learnt[0], 0, -1);
					} else {
						// Learnt clause
						// Add a clause to clause database
						int cref = add_clause(learnt);
						clauseDB[cref].lbd = lbd;

						// Assign
						assign(learnt[0], backtrackLevel, cref); 
					}

					// var_decay for locality
					var_inc *= (1 / var_decay);

					// Parameter update
					++ conflicts, ++ reduces;
					
					// Update the local-best phase
					if ( (int)trail.size() > threshold ) {
						threshold = trail.size();
						for ( int i = 1; i < vars + 1; i ++ ) local_best[i] = value[i];
					}
				}
			} else if ( reduces >= reduce_limit ) {
				reduce();
			} else if ( lbd_queue_size == 50 && 0.8*fast_lbd_sum/lbd_queue_size > slow_lbd_sum/conflicts ) {
				restart();
			} else if ( conflicts >= rephase_limit ) {
				rephase();
			} else {
				res = decide();
			}
		} else res = 30;
	}

	if ( res == 10 || res == 20 ) {
		double processFinal = timeCheckerCPU();
		processTimeFinal = processFinal - processStart;
		printf( "Elapsed Time [Total] (CPU): %.4f\n", processTimeFinal );
		//printf( "Elapsed Time [Propa] (CPU): %.4f\n", propagaTimeFinal );
		printf( "Elapsed Time [MaxBCP] (CPU): %.4f\n", maxBCPTime );
		printf( "----------------------------------------------------\n" );
	}

	return res;
}

// Print model when the result is SAT
void Solver::printModel() {
    	for ( int i = 1; i <= vars; i++ ) printf("%d ", value[i] * i);
    	printf( "0\n" );
}
