"""Freeze public Disaster Clippy source passages for the local RAG comparison."""
import argparse
import hashlib
import json
from pathlib import Path

SELECTED = [
    ('builditsolar', 'd9d0c8106c91d87010956c2c613d40a8', 'Batch Water Heaters', 0, 550),
    ('builditsolar', '06d54b7b338a3c91a617d31f72b37f4e', "I'm pleased to report", 150, 450),
    ('builditsolar', '9afc2d0f4cea0e02339fd09f443b4cc7', 'storm window', 0, 500),
    ('builditsolar', '90cee3cf9c5a6928cf210b053ccbf738', 'high lift', 0, 500),
    ('wiki_top_100', 'a43a2fafe35604dcbac8bc1fe906c394', 'Solar eclipse', 0, 580),
    ('wiki_top_100', 'a324bd81be9a051a4c233c3ba52f1329', 'Antarctica', 0, 500),
    ('wiki_top_100', '216af0bce6afaec1497474d7984d5daa', 'California gold rush', 0, 500),
    ('wiki_top_100', '6f55b7ddf7765784271179c7931aa425', 'Elvis Presley', 0, 500),
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    indexes = {}
    passages = []
    for source, doc_id, anchor, before, after in SELECTED:
        if source not in indexes:
            indexes[source] = json.loads((args.source_root / source / '_index.json').read_text(encoding='utf-8'))['documents']
        item = indexes[source][doc_id]
        content = item['content']
        at = content.lower().find(anchor.lower())
        if at < 0:
            raise ValueError(f'{source}:{doc_id}: missing anchor {anchor}')
        start, end = max(0, at-before), min(len(content), at+after)
        passage = {
            'id': f'{source}:{doc_id}', 'source': source, 'document_id': doc_id,
            'title': item['title'], 'url': item.get('url'),
            'text': content[start:end].replace('\xa0', ' '),
            'source_offset': start, 'source_end': end,
            'source_content_sha256': hashlib.sha256(content.encode()).hexdigest(),
        }
        passages.append(passage)
    payload = {'version': 1, 'embedding_model': 'all-mpnet-base-v2',
               'source_root_kind': 'Disaster Clippy local public source packs',
               'passages': passages}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    payload['corpus_sha256'] = hashlib.sha256(canonical).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('output', args.output, 'passages', len(passages), 'sha256', payload['corpus_sha256'])


if __name__ == '__main__':
    main()
