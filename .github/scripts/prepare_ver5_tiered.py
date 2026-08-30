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


header = "cpu/ver_5/solver.h"
source = "cpu/ver_5/solver.cpp"
main = "cpu/ver_5/main.cpp"

replace_once(
	header,
	"#define WatchedLiterals(id) (watched_literals[vars + id])\n\n\n// Heap data structure (max heap)",
	"#define WatchedLiterals(id) (watched_literals[vars + id])\n\n\n"
	"enum ClauseTier {\n"
	"\tCLAUSE_ORIGINAL = 0,\n"
	"\tCLAUSE_CORE = 1,\n"
	"\tCLAUSE_TIER2 = 2,\n"
	"\tCLAUSE_LOCAL = 3\n"
	"};\n\n\n"
	"// Heap data structure (max heap)",
)
replace_once(
	header,
	"\t// The number of conflict-analysis uses\n\tuint32_t useCount;\n    \t// Literals in a clause",
	"\t// The number of conflict-analysis uses\n"
	"\tuint32_t useCount;\n"
	"\t// Learned-clause retention tier\n"
	"\tint tier;\n"
	"\t// Last conflict where the clause participated in analysis\n"
	"\tint touched;\n"
	"    \t// Literals in a clause",
)
replace_once(
	header,
	"    \tClause( int sz ): lbd(0), activity(0.0), useCount(0) { literals.resize(sz); }",
	"    \tClause( int sz ): lbd(0), activity(0.0), useCount(0),\n"
	"\t                       tier(CLAUSE_ORIGINAL), touched(0) { literals.resize(sz); }",
)
replace_once(
	header,
	"    \tint rephase_inc, rephase_limit, reduce_limit;   // Parameters for rephase and reduce",
	"    \tint rephase_inc, rephase_limit, reduce_limit, reduceStep;\n"
	"\tint coreLBDLimit, tier2LBDLimit, tier2StaleLimit;",
)
replace_once(
	header,
	"\tlong long clauseActivityBumps, dynamicLBDUpdates;",
	"\tlong long clauseActivityBumps, dynamicLBDUpdates;\n"
	"\tlong long corePromotions, tier2Promotions, tier2Demotions;",
)
replace_once(
	header,
	"\tvoid update_score( int var, double coeff );               // Update variable activity\n"
	"\tvoid bumpClauseActivity( int cref );                       // Update learnt-clause activity",
	"\tvoid update_score( int var, double coeff );               // Update variable activity\n"
	"\tint  selectClauseTier( int lbd ) const;                    // Select tier from LBD\n"
	"\tvoid initializeLearnedClause( int cref, int lbd );         // Initialize learned-clause tier\n"
	"\tvoid updateClauseTier( int cref );                         // Promote a learned clause\n"
	"\tvoid bumpClauseActivity( int cref );                       // Update learnt-clause activity",
)

replace_once(
	source,
	"        clauseActivityBumps = dynamicLBDUpdates = 0;\n",
	"        clauseActivityBumps = dynamicLBDUpdates = 0;\n"
	"        corePromotions = tier2Promotions = tier2Demotions = 0;\n",
)
replace_once(
	source,
	"        rephase_inc = 100000;\n"
	"        rephase_limit = 100000;\n"
	"        reduce_limit = 8192;\n",
	"        rephase_inc = 100000;\n"
	"        rephase_limit = 100000;\n"
	"        reduce_limit = 8192;\n"
	"        reduceStep = 512;\n"
	"        coreLBDLimit = 3;\n"
	"        tier2LBDLimit = 6;\n"
	"        tier2StaleLimit = 30000;\n"
	"        if ( const char *env = getenv(\"UATU_REDUCE_INITIAL\") ) {\n"
	"                const int parsed = atoi(env);\n"
	"                if ( parsed > 0 ) reduce_limit = parsed;\n"
	"        }\n"
	"        if ( const char *env = getenv(\"UATU_REDUCE_STEP\") ) {\n"
	"                const int parsed = atoi(env);\n"
	"                if ( parsed > 0 ) reduceStep = parsed;\n"
	"        }\n"
	"        if ( const char *env = getenv(\"UATU_CORE_LBD\") ) {\n"
	"                const int parsed = atoi(env);\n"
	"                if ( parsed > 0 ) coreLBDLimit = parsed;\n"
	"        }\n"
	"        if ( const char *env = getenv(\"UATU_TIER2_LBD\") ) {\n"
	"                const int parsed = atoi(env);\n"
	"                if ( parsed >= coreLBDLimit ) tier2LBDLimit = parsed;\n"
	"        }\n"
	"        if ( const char *env = getenv(\"UATU_TIER2_STALE\") ) {\n"
	"                const int parsed = atoi(env);\n"
	"                if ( parsed > 0 ) tier2StaleLimit = parsed;\n"
	"        }\n"
	"        if ( tier2LBDLimit < coreLBDLimit ) tier2LBDLimit = coreLBDLimit;\n",
)
replace_once(
	source,
	"        vsids.initialize(activity);\n"
	"        lbdMark[0] = 0;\n"
	"        for ( int i = 1; i <= vars; i ++ ) {\n"
	"                value[i] = local_best[i] = saved[i] = 0;\n"
	"                reason[i] = level[i] = mark[i] = 0;\n"
	"                lbdMark[i] = 0;\n"
	"                activity[i] = 0.0;\n"
	"                vsids.insert(i);\n"
	"        }",
	"        vsids.initialize(activity);\n"
	"        value[0] = local_best[0] = saved[0] = 0;\n"
	"        reason[0] = -1;\n"
	"        level[0] = mark[0] = 0;\n"
	"        lbdMark[0] = 0;\n"
	"        activity[0] = 0.0;\n"
	"        for ( int i = 1; i <= vars; i ++ ) {\n"
	"                value[i] = local_best[i] = saved[i] = 0;\n"
	"                reason[i] = -1;\n"
	"                level[i] = mark[i] = 0;\n"
	"                lbdMark[i] = 0;\n"
	"                activity[i] = 0.0;\n"
	"                vsids.insert(i);\n"
	"        }",
)

clause_tier_methods = """// Select a learned-clause tier from its current LBD
int Solver::selectClauseTier( int lbd ) const {
	if ( lbd > 0 && lbd <= coreLBDLimit ) return CLAUSE_CORE;
	if ( lbd > 0 && lbd <= tier2LBDLimit ) return CLAUSE_TIER2;
	return CLAUSE_LOCAL;
}

// Initialize tier metadata for a newly learned clause
void Solver::initializeLearnedClause( int cref, int lbd ) {
	Clause &clause = clauseDB[cref];
	clause.lbd = lbd;
	clause.tier = selectClauseTier(lbd);
	clause.touched = conflicts;
}

// Promote a learned clause when its dynamic LBD crosses a tier boundary
void Solver::updateClauseTier( int cref ) {
	Clause &clause = clauseDB[cref];
	const int newTier = selectClauseTier(clause.lbd);
	if ( newTier >= clause.tier ) return;

	if ( newTier == CLAUSE_CORE ) {
		corePromotions ++;
	} else if ( newTier == CLAUSE_TIER2 ) {
		tier2Promotions ++;
	}
	clause.tier = newTier;
}

"""
replace_once(
	source,
	"// Update learnt-clause activity\nvoid Solver::bumpClauseActivity",
	clause_tier_methods + "// Update learnt-clause activity\nvoid Solver::bumpClauseActivity",
)

update_quality = """// Update learnt-clause usage, dynamic LBD, and tier
void Solver::updateClauseQuality( int cref ) {
	if ( cref < origin_clauses || cref >= static_cast<int>(clauseDB.size()) ) return;

	bumpClauseActivity(cref);

	Clause &clause = clauseDB[cref];
	clause.touched = conflicts;
	const int currentLBD = calculateClauseLBD(clause);
	if ( currentLBD > 0 && (clause.lbd == 0 || currentLBD < clause.lbd) ) {
		clause.lbd = currentLBD;
		dynamicLBDUpdates ++;
	}
	updateClauseTier(cref);
}

"""
replace_region(
	source,
	"// Update learnt-clause usage and dynamic LBD\nvoid Solver::updateClauseQuality",
	"// Conflict analysis\nint Solver::analyze",
	update_quality,
)
replace_once(
	source,
	"        // Preserve the original solver's conflict-level convention.\n"
	"        const int conflictLevel = level[abs(clauseDB[conflict][0])];",
	"        // First-UIP analysis always starts at the current decision level.\n"
	"        const int conflictLevel = static_cast<int>(decVarInTrail.size());",
)
replace_once(
	source,
	"                        if ( level[variable] >= conflictLevel ) ++unresolved;",
	"                        if ( level[variable] == conflictLevel ) ++unresolved;",
)
replace_once(
	source,
	"\t\t\tint v = abs(trail[i]);\n\t\t\tvalue[v] = 0;\n\n\t\t\t// Phase saving",
	"\t\t\tint v = abs(trail[i]);\n"
	"\t\t\tvalue[v] = 0;\n"
	"\t\t\treason[v] = -1;\n"
	"\t\t\tlevel[v] = 0;\n\n"
	"\t\t\t// Phase saving",
)

reduce_body = """// Tiered learned-clause reduction
void Solver::reduce() {
	backtrack(0);
	reduces = 0;
	reduce_limit += reduceStep;
	reductionRuns ++;

	const int oldSize = static_cast<int>(clauseDB.size());
	reduceMap.assign(oldSize, -1);

	std::vector<unsigned char> locked(oldSize, 0);
	for ( int literal : trail ) {
		const int clause = reason[abs(literal)];
		if ( clause >= origin_clauses && clause < oldSize ) locked[clause] = 1;
	}

	std::vector<int> localCandidates;
	localCandidates.reserve(oldSize - origin_clauses);
	for ( int i = origin_clauses; i < oldSize; i ++ ) {
		Clause &clause = clauseDB[i];
		if ( locked[i] || clause.tier == CLAUSE_CORE ) continue;

		if ( clause.tier == CLAUSE_TIER2 ) {
			const int age = conflicts - clause.touched;
			if ( age <= tier2StaleLimit ) continue;
			clause.tier = CLAUSE_LOCAL;
			tier2Demotions ++;
		}

		localCandidates.push_back(i);
	}

	std::sort(localCandidates.begin(), localCandidates.end(), [&]( int a, int b ) {
		if ( clauseDB[a].activity != clauseDB[b].activity ) {
			return clauseDB[a].activity < clauseDB[b].activity;
		}
		if ( clauseDB[a].lbd != clauseDB[b].lbd ) {
			return clauseDB[a].lbd > clauseDB[b].lbd;
		}
		if ( clauseDB[a].literals.size() != clauseDB[b].literals.size() ) {
			return clauseDB[a].literals.size() > clauseDB[b].literals.size();
		}
		if ( clauseDB[a].touched != clauseDB[b].touched ) {
			return clauseDB[a].touched < clauseDB[b].touched;
		}
		return a < b;
	});

	std::vector<unsigned char> erase(oldSize, 0);
	const size_t deleteCount = localCandidates.size() / 2;
	for ( size_t i = 0; i < deleteCount; i ++ ) erase[localCandidates[i]] = 1;
	deletedClauses += static_cast<long long>(deleteCount);

	int newSize = origin_clauses;
	for ( int i = 0; i < origin_clauses; i ++ ) reduceMap[i] = i;
	for ( int i = origin_clauses; i < oldSize; i ++ ) {
		if ( erase[i] ) continue;
		if ( newSize != i ) clauseDB[newSize] = std::move(clauseDB[i]);
		reduceMap[i] = newSize ++;
	}
	clauseDB.erase(clauseDB.begin() + newSize, clauseDB.end());

	for ( int literal : trail ) {
		const int variable = abs(literal);
		if ( reason[variable] >= origin_clauses ) {
			reason[variable] = reduceMap[reason[variable]];
		}
	}

	for ( int literal = -vars; literal <= vars; literal ++ ) {
		if ( literal == 0 ) continue;
		std::vector<WL> &watchers = WatchedLiterals(literal);
		int out = 0;
		for ( int i = 0; i < static_cast<int>(watchers.size()); i ++ ) {
			const int oldIndex = watchers[i].clauseIdx;
			const int newIndex = oldIndex < origin_clauses
				? oldIndex : reduceMap[oldIndex];
			if ( newIndex == -1 ) continue;
			watchers[i].clauseIdx = newIndex;
			if ( out != i ) watchers[out] = watchers[i];
			out ++;
		}
		watchers.resize(out);
	}
}

"""
replace_region(
	source,
	"// Clause deletion\nvoid Solver::reduce()",
	"// Solver\nint Solver::solve()",
	reduce_body,
)
replace_once(
	source,
	"                                const int learnedClause = add_clause(learnt);\n"
	"                                clauseDB[learnedClause].lbd = lbd;\n"
	"                                assign(learnt[0], backtrackLevel, learnedClause);",
	"                                const int learnedClause = add_clause(learnt);\n"
	"                                initializeLearnedClause(learnedClause, lbd);\n"
	"                                assign(learnt[0], backtrackLevel, learnedClause);",
)

replace_once(
	main,
	"\tprintf( \"----------------------------------------------------\\n\" );\n"
	"\tprintf( \"Conflicts            : %d\\n\", solver.conflicts );",
	"\tsize_t coreClauses = 0;\n"
	"\tsize_t tier2Clauses = 0;\n"
	"\tsize_t localClauses = 0;\n"
	"\tfor ( int i = solver.origin_clauses;\n"
	"\t      i < static_cast<int>(solver.clauseDB.size()); i ++ ) {\n"
	"\t\tif ( solver.clauseDB[i].tier == CLAUSE_CORE ) coreClauses ++;\n"
	"\t\telse if ( solver.clauseDB[i].tier == CLAUSE_TIER2 ) tier2Clauses ++;\n"
	"\t\telse if ( solver.clauseDB[i].tier == CLAUSE_LOCAL ) localClauses ++;\n"
	"\t}\n\n"
	"\tprintf( \"----------------------------------------------------\\n\" );\n"
	"\tprintf( \"Conflicts            : %d\\n\", solver.conflicts );",
)
replace_once(
	main,
	"\tprintf( \"Dynamic LBD Updates  : %lld\\n\", solver.dynamicLBDUpdates );\n"
	"\tprintf( \"Active Clauses       : %zu\\n\", solver.clauseDB.size() );",
	"\tprintf( \"Dynamic LBD Updates  : %lld\\n\", solver.dynamicLBDUpdates );\n"
	"\tprintf( \"Core Promotions      : %lld\\n\", solver.corePromotions );\n"
	"\tprintf( \"Tier2 Promotions     : %lld\\n\", solver.tier2Promotions );\n"
	"\tprintf( \"Tier2 Demotions      : %lld\\n\", solver.tier2Demotions );\n"
	"\tprintf( \"Core Clauses         : %zu\\n\", coreClauses );\n"
	"\tprintf( \"Tier2 Clauses        : %zu\\n\", tier2Clauses );\n"
	"\tprintf( \"Local Clauses        : %zu\\n\", localClauses );\n"
	"\tprintf( \"Active Clauses       : %zu\\n\", solver.clauseDB.size() );",
)

Path("cpu/ver_5/README.md").write_text(
	"# Uatu Ver. 5\n\n"
	"Tiered learned-clause management built directly on Ver. 3.\n\n"
	"## Architecture\n\n"
	"- Retains the Ver. 3 BCP, First-UIP learning, VSIDS branching, one-step minimization, and search-control pipeline.\n"
	"- Keeps learned clauses with LBD at most 3 permanently in the CORE tier.\n"
	"- Places learned clauses with LBD from 4 through 6 in TIER2 and protects them while they are used recently.\n"
	"- Demotes TIER2 clauses that are unused for 30,000 conflicts to LOCAL.\n"
	"- Deletes the lower-activity half of unlocked LOCAL clauses at each reduction.\n"
	"- Promotes clauses when dynamic LBD improvement crosses a tier boundary.\n"
	"- Does not enable CHB branching or recursive minimization.\n"
)

root_readme = Path("README.md").read_text()
version_anchor = (
	"| `cpu/ver_2` | Improved solver preserving the original search policy, with lower profiling overhead, "
	"one-step learned-clause minimization, and deterministic clause reduction |\n"
)
if version_anchor not in root_readme:
	raise SystemExit("missing root README version-table anchor")
root_readme = root_readme.replace(
	version_anchor,
	version_anchor
	+ "| `cpu/ver_3` | Usage-aware learned-clause retention with activity and dynamic LBD updates |\n"
	+ "| `cpu/ver_4` | Ver. 3 with CHB decision selection |\n"
	+ "| `cpu/ver_5` | Ver. 3 with CORE, TIER2, and LOCAL learned-clause management |\n",
	1,
)
root_readme = root_readme.replace(
	"cd cpu/ver_1   # or cpu/ver_2",
	"cd cpu/ver_1   # or cpu/ver_2, cpu/ver_3, cpu/ver_4, or cpu/ver_5",
	1,
)
Path("README.md").write_text(root_readme)
