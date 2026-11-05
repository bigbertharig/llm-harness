"""Local-only MCP retrieval fixture over an isolated Chroma collection.

The source packs and production Chroma directories are never opened by this
server. It consumes the frozen, public eight-passage corpus beside this file.
"""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit

import chromadb
from sentence_transformers import SentenceTransformer

TOOL = {'name': 'search_passages',
        'description': 'Search the frozen local Disaster Clippy passages by meaning. Returns ranked passage IDs, source IDs, titles, snippets, and cosine distance. Use source to limit the search to one installed source.',
        'inputSchema': {'type': 'object', 'properties': {
            'query': {'type': 'string', 'minLength': 3, 'maxLength': 500},
            'source': {'type': 'string', 'enum': ['builditsolar', 'wiki_top_100']},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 5}},
            'required': ['query'], 'additionalProperties': False}}


class RagIndex:
    def __init__(self, corpus_path, model_path, db_path, receipt_dir):
        self.receipt_dir = receipt_dir
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        payload = json.loads(corpus_path.read_text(encoding='utf-8'))
        declared = payload.pop('corpus_sha256')
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')).encode()
        actual = hashlib.sha256(canonical).hexdigest()
        if actual != declared:
            raise ValueError('frozen corpus hash mismatch')
        self.corpus_sha256 = actual
        self.passages = payload['passages']
        self.model = SentenceTransformer(str(model_path), local_files_only=True)
        self.client = chromadb.PersistentClient(path=str(db_path))
        self.collection = self.client.get_or_create_collection(
            'rag_fixture_v1', metadata={'hnsw:space': 'cosine', 'corpus_sha256': actual})
        if self.collection.count() == 0:
            embeddings = self.model.encode([x['text'] for x in self.passages],
                                           normalize_embeddings=True).tolist()
            self.collection.add(ids=[x['id'] for x in self.passages],
                documents=[x['text'] for x in self.passages],
                embeddings=embeddings,
                metadatas=[{'source': x['source'], 'title': x['title'],
                            'url': x.get('url') or '', 'document_id': x['document_id']}
                           for x in self.passages])
        if self.collection.count() != len(self.passages):
            raise RuntimeError('isolated Chroma collection has a wrong count')
        if self.collection.metadata.get('corpus_sha256') != actual:
            raise RuntimeError('isolated Chroma collection has a wrong corpus hash')

    def search(self, args):
        unknown = set(args) - {'query', 'source', 'limit'}
        query, source, limit = args.get('query'), args.get('source'), args.get('limit', 3)
        if unknown or not isinstance(query, str) or not 3 <= len(query) <= 500 \
                or source not in (None, 'builditsolar', 'wiki_top_100') \
                or type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError('invalid search_passages arguments')
        started = time.monotonic()
        vector = self.model.encode([query], normalize_embeddings=True).tolist()
        response = self.collection.query(query_embeddings=vector, n_results=limit,
            where={'source': source} if source else None,
            include=['documents', 'metadatas', 'distances'])
        results = []
        for ident, text, metadata, distance in zip(response['ids'][0],
                response['documents'][0], response['metadatas'][0], response['distances'][0]):
            results.append({'id': ident, 'source': metadata['source'],
                            'title': metadata['title'], 'url': metadata['url'],
                            'snippet': text, 'distance': round(float(distance), 6)})
        return {'results': results, 'corpus_sha256': self.corpus_sha256,
                'embedding_model': 'all-mpnet-base-v2',
                'duration_ms': round((time.monotonic()-started)*1000, 1)}


def self_test(index):
    cases = [
        ('Why drain simple batch solar water heaters in a cold winter?', 'builditsolar:d9d0c8106c91d87010956c2c613d40a8', None),
        ('What stopped the undershoot water wheel from working?', 'builditsolar:06d54b7b338a3c91a617d31f72b37f4e', None),
        ('Why does the Moon not completely cover the Sun in an annular solar eclipse?', 'wiki_top_100:a43a2fafe35604dcbac8bc1fe906c394', None),
        ('What covers the Sun during a total eclipse?', 'wiki_top_100:a43a2fafe35604dcbac8bc1fe906c394', 'wiki_top_100'),
    ]
    rows = []
    for query, expected, source in cases:
        result = index.search({'query': query, 'source': source, 'limit': 3})
        ranked = [x['id'] for x in result['results']]
        rows.append({'query': query, 'source_filter': source, 'expected': expected,
                     'ranked_ids': ranked, 'hit_at_3': expected in ranked,
                     'top_1': ranked[0] == expected,
                     'duration_ms': result['duration_ms']})
    receipt = {'corpus_sha256': index.corpus_sha256, 'embedding_model': 'all-mpnet-base-v2',
               'passage_count': len(index.passages), 'cases': rows,
               'passed': all(x['hit_at_3'] for x in rows)}
    (index.receipt_dir / 'rag_direct_control.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2), flush=True)
    return receipt['passed']


def serve(index, bind, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == '/calls':
                run_id = parse_qs(parsed.query).get('run', [''])[0]
                path = index.receipt_dir / 'rag_calls.jsonl'
                rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
                self.reply(200, {'calls': [x for x in rows if x.get('run') == run_id]})
                return
            if parsed.path != '/health':
                self.send_error(404)
                return
            self.reply(200, {'ok': True, 'corpus_sha256': index.corpus_sha256,
                             'passages': len(index.passages)})
        def reply(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path != '/mcp':
                self.send_error(404)
                return
            try:
                packet = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method, ident = packet.get('method'), packet.get('id')
                if method == 'notifications/initialized':
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == 'initialize':
                    result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                              'serverInfo': {'name': 'local-rag-fixture', 'version': '1'}}
                elif method == 'tools/list':
                    result = {'tools': [TOOL]}
                elif method == 'tools/call':
                    params = packet.get('params') or {}
                    if params.get('name') != 'search_passages':
                        raise ValueError('unknown tool')
                    data = index.search(params.get('arguments') or {})
                    result = {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(data)}],
                              'structuredContent': data}
                    with (index.receipt_dir / 'rag_calls.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps({'run': parse_qs(parsed.query).get('run', [''])[0],
                                                 'method': 'tools/call',
                                                 'arguments': params['arguments'],
                                                 'ids': [x['id'] for x in data['results']],
                                                 'duration_ms': data['duration_ms']}) + '\n')
                else:
                    self.reply(200, {'jsonrpc': '2.0', 'id': ident,
                                     'error': {'code': -32601, 'message': 'Method not found'}})
                    return
                self.reply(200, {'jsonrpc': '2.0', 'id': ident, 'result': result})
            except Exception as exc:
                self.reply(200, {'jsonrpc': '2.0', 'id': packet.get('id'),
                                 'error': {'code': -32602, 'message': f'{type(exc).__name__}: {exc}'}})
    http = ThreadingHTTPServer((bind, port), Handler)
    print(json.dumps({'ready': True, 'bind': bind, 'port': port,
                      'corpus_sha256': index.corpus_sha256}), flush=True)
    http.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=17021)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--receipt-dir', type=Path, required=True)
    args = parser.parse_args()
    index = RagIndex(args.corpus, args.model, args.db, args.receipt_dir)
    if args.self_test:
        raise SystemExit(0 if self_test(index) else 1)
    serve(index, args.bind, args.port)
