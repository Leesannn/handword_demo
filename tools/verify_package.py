"""Check packaged source provenance, Python syntax, JSON and local Markdown links."""
from pathlib import Path
import hashlib
import json
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def verify():
    counts = dict(python=0, json=0, markdown=0, local_links=0, source_hashes=0)
    for path in ROOT.rglob('*'):
        if not path.is_file() or set(path.relative_to(ROOT).parts) & {
            '.git', '.venv', '__pycache__', 'node_modules', 'Pods', 'DerivedData', 'runtime'
        }:
            continue
        if path.suffix == '.py':
            compile(path.read_bytes(), str(path), 'exec')
            counts['python'] += 1
        if path.suffix == '.json':
            json.loads(path.read_text(encoding='utf-8-sig'))
            counts['json'] += 1
        if path.suffix == '.md':
            text = path.read_text(encoding='utf-8-sig')
            assert len(re.findall(r'^```', text, re.M)) % 2 == 0, path
            counts['markdown'] += 1
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                if '://' in target or target.startswith('mailto:'):
                    continue
                local, _, anchor = target.partition('#')
                destination = (path.parent / unquote(local)) if local else path
                assert destination.exists(), (path.relative_to(ROOT), target)
                if anchor and destination.is_file():
                    headings = re.findall(r'^#{1,6}\s+(.+)$', destination.read_text(encoding='utf-8-sig'), re.M)
                    anchors = [re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headings]
                    assert anchor in anchors, (path.relative_to(ROOT), target)
                counts['local_links'] += 1
    provenance = json.loads((ROOT / 'evidence/source-inventory.json').read_text(encoding='utf-8-sig'))
    for source in provenance['files']:
        path = ROOT / source['destination']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256'], path
        counts['source_hashes'] += 1
    return counts


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
