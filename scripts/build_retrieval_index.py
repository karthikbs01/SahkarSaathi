"""Build/reuse a local ACTIVE-only FAISS index. Run with --force to re-embed."""
import argparse
from collections import Counter
import csv
import importlib.metadata
import json
from pathlib import Path
import tempfile

from retrieval_common import (DEFAULT_CONFIG, DOCUMENTS, SOURCES, INDEX_DIR,
                              digest, fingerprint, load_config, load_model, valid_manifest)


def embedding_windows(record, tokenizer, config):
    text = record['text']
    tokens = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                       truncation=False, verbose=False)
    offsets = tokens['offset_mapping']
    if not offsets:
        raise ValueError(f'No text tokens: {record["chunk_id"]}')
    # Metadata occupies at most a third of the source token count, capped at 64.
    fields = ('title', 'jurisdiction', 'part', 'chapter', 'section', 'subsection',
              'rule', 'subrule', 'clause', 'heading', 'subheading', 'topics')
    context = []
    budget = min(config['context_token_limit'], len(offsets) // 3)
    for key in fields:
        value = record.get(key)
        if value:
            value = ', '.join(value) if isinstance(value, list) else str(value)
            line = f'{key.replace("_", " ").title()}: {value}'
            candidate = '\n'.join(context + [line])
            if len(tokenizer.encode(candidate, add_special_tokens=False)) <= budget:
                context.append(line)
    header = '\n'.join(context)
    prefix = config['passage_prefix'] + (header + '\n' if header else '') + 'Text: '
    room = config['max_seq_length'] - len(tokenizer.encode(prefix)) - 8
    width = min(config['body_window_tokens'], room)
    if width < 1:
        raise ValueError('Context leaves no room for source text')
    windows, weights = [], []
    for start in range(0, len(offsets), width):
        end = min(start + width, len(offsets))
        left = 0 if start == 0 else offsets[start][0]
        right = len(text) if end == len(offsets) else offsets[end][0]
        passage = prefix + text[left:right]
        if len(tokenizer.encode(passage)) > config['max_seq_length']:
            raise ValueError(f'Window would truncate: {record["chunk_id"]}')
        windows.append(passage)
        weights.append(end - start)
    return windows, weights


def build(config, force=False, folder=INDEX_DIR):
    import faiss
    import numpy as np
    signature, inputs = fingerprint(config)
    folder.mkdir(parents=True, exist_ok=True)
    cached = valid_manifest(folder, signature)
    if cached and not force:
        index = faiss.read_index(str(folder / 'index.faiss'))
        if index.ntotal == cached['active_records_indexed'] and index.d == config['embedding_dimension']:
            print(json.dumps({'index_reused': True, **cached['counts']}))
            return cached
    with SOURCES.open(encoding='utf-8-sig', newline='') as stream:
        sources = {r['source_id']: r for r in csv.DictReader(stream)}
    print(f'Loading local embedding model: {config["model_name"]}', flush=True)
    model = load_model(config)
    index = faiss.IndexFlatIP(config['embedding_dimension'])
    counts = Counter()
    source_counts = Counter()
    seen = set()
    with tempfile.TemporaryDirectory(prefix='build-', dir=folder) as temp:
        stage = Path(temp)
        with (stage / 'metadata.jsonl').open('w', encoding='utf-8', newline='\n') as mapping:
            batch = []

            def embed_batch():
                if not batch:
                    return
                passages, owners, weights = [], [], []
                for i, record in enumerate(batch):
                    windows, sizes = embedding_windows(record, model.tokenizer, config)
                    counts['embedding_windows'] += len(windows)
                    counts['multi_window_chunks'] += len(windows) > 1
                    passages.extend(windows)
                    owners.extend([i] * len(windows))
                    weights.extend(sizes)
                vectors = model.encode(passages, batch_size=config['batch_size'],
                                       normalize_embeddings=True, show_progress_bar=False,
                                       convert_to_numpy=True)
                pooled = np.zeros((len(batch), config['embedding_dimension']), dtype='float32')
                for vector, owner, weight in zip(vectors, owners, weights):
                    pooled[owner] += vector * weight
                faiss.normalize_L2(pooled)
                if not np.isfinite(pooled).all() or (np.linalg.norm(pooled, axis=1) < .99).any():
                    raise ValueError('Invalid embedding vectors')
                index.add(pooled)
                for record in batch:
                    metadata = {k: v for k, v in record.items() if k != 'text'}
                    metadata['text_preview'] = record['text'][:250]
                    mapping.write(json.dumps(metadata, ensure_ascii=False) + '\n')
                print(f'Embedded ACTIVE records: {index.ntotal}', flush=True)
                batch.clear()

            with DOCUMENTS.open(encoding='utf-8') as stream:
                for line in stream:
                    record = json.loads(line)
                    counts['total_jsonl_records'] += 1
                    status = record.get('retrieval_status')
                    if status not in {'ACTIVE', 'REFERENCE_ONLY', 'REVIEW'}:
                        raise ValueError('Missing/invalid retrieval_status')
                    if status != 'ACTIVE':
                        counts['records_excluded'] += 1
                        continue
                    sid, cid = record['source_id'], record['chunk_id']
                    if sid not in sources or cid in seen or not record['text'].strip():
                        raise ValueError(f'Invalid ACTIVE record: {cid}')
                    if record['jurisdiction'] != sources[sid]['jurisdiction']:
                        raise ValueError(f'Jurisdiction metadata mismatch: {cid}')
                    seen.add(cid)
                    source_counts[sid] += 1
                    batch.append(record)
                    if len(batch) == config['batch_size']:
                        embed_batch()
                embed_batch()
        if not index.ntotal:
            raise ValueError('No ACTIVE records to index')
        if digest(DOCUMENTS) != inputs['documents'] or digest(SOURCES) != inputs['sources']:
            raise ValueError('Inputs changed during indexing')
        faiss.write_index(index, str(stage / 'index.faiss'))
        counts['active_records_indexed'] = index.ntotal
        counts['sources_represented'] = len(source_counts)
        manifest = {'fingerprint': signature, 'inputs': inputs, 'config': config,
                    'active_records_indexed': index.ntotal, 'counts': dict(counts),
                    'source_counts': dict(source_counts), 'metric': 'cosine via normalized IndexFlatIP',
                    'packages': {p: importlib.metadata.version(p) for p in
                                 ['sentence-transformers', 'faiss-cpu', 'torch', 'transformers', 'numpy']},
                    'artifacts': {name: digest(stage / name) for name in ['index.faiss', 'metadata.jsonl']}}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        # Manifest committed last: interrupted replacement cannot pass integrity validation.
        for name in ['index.faiss', 'metadata.jsonl', 'manifest.json']:
            (stage / name).replace(folder / name)
    print(json.dumps({'index_reused': False, **manifest['counts'], 'source_counts': dict(source_counts)}))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    build(load_config(args.config), args.force)
