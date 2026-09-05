import json
import re
from pathlib import Path

anomalies = []
for path in Path('paired').rglob('result.json'):
    case = json.loads(path.read_text())
    log = path.parent / 'ver4.log'
    text = log.read_text(errors='replace')
    counters = {}
    for name in ['Conflicts', 'Decisions', 'Unit Propagations', 'BCP Calls', 'Restarts', 'Rephases', 'Clause Reductions']:
        match = re.search(r'^' + re.escape(name) + r'\s*:\s*(-?\d+)', text, re.M)
        if match and int(match.group(1)) < 0:
            counters[name] = int(match.group(1))
    if counters:
        anomalies.append({'index': case['index'], 'hash': case['hash'], 'filename': case['filename'],
                          'negative_counters': counters})
anomalies.sort(key=lambda row: row['index'])
result = {'negative_counter_cases': len(anomalies), 'cases': anomalies,
          'scope': 'Only completed stdout summaries can be checked; killed processes may have no summary.'}
Path('final').mkdir(exist_ok=True)
Path('final/counter_check.json').write_text(json.dumps(result, indent=2) + '\n')
print('COUNTER_CHECK_BEGIN')
print(json.dumps(result, indent=2))
print('COUNTER_CHECK_END')
