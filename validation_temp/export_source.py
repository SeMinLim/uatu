import hashlib
import json
import os
from pathlib import Path
import urllib.request

entries = []
expected = {}
for line in Path('source.sha256').read_text().splitlines():
    digest, path = line.split(None, 1)
    expected[path.strip()] = digest
paths = sorted(p for p in Path('cpu/ver_5').rglob('*') if p.is_file())
assert {str(p) for p in paths} == set(expected)
for path in paths:
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == expected[str(path)]
    payload = json.dumps({'content': data.decode('utf-8'), 'encoding': 'utf-8'}).encode()
    request = urllib.request.Request('https://api.github.com/repos/SeMinLim/uatu/git/blobs',
                                    data=payload, method='POST',
                                    headers={'Authorization': 'Bearer '+os.environ['GH_TOKEN'],
                                             'Accept': 'application/vnd.github+json',
                                             'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        blob = json.load(response)
    header = ('blob '+str(len(data))+'\0').encode()
    assert hashlib.sha1(header+data).hexdigest() == blob['sha']
    entries.append({'path': str(path), 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
print('VERIFIED_SOURCE_BLOBS_BEGIN')
print(json.dumps(entries, indent=2))
print('VERIFIED_SOURCE_BLOBS_END')
Path('source-blobs.json').write_text(json.dumps(entries, indent=2)+'\n')
