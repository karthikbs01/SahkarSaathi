"""Synthetic tests; no corpus fixture tuning or model download."""
import unittest
import json
from pathlib import Path
import re
import tempfile
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import numpy as np
import faiss
from build_retrieval_index import embedding_windows
import build_retrieval_index as builder
from evaluate_retrieval import scoped_search
from retrieval_common import allowed_jurisdictions, source_hits, digest, valid_manifest


class WordTokenizer:
    def encode(self, text, **kwargs):
        return text.split()

    def __call__(self, text, **kwargs):
        return {'offset_mapping': [(m.start(), m.end()) for m in re.finditer(r'\S+', text)]}


class RetrievalTests(unittest.TestCase):
    def test_scope_before_topk(self):
        index = faiss.IndexFlatIP(2)
        index.add(np.array([[1, 0], [.9, .1], [.8, .2], [.7, .3]], dtype='float32'))
        metadata = [dict(chunk_id=str(i), jurisdiction=j) for i, j in enumerate(
            ['Maharashtra', 'Maharashtra', 'Central', 'Karnataka'])]
        hits = scoped_search(index, metadata, np.array([1, 0]), allowed_jurisdictions('Karnataka'), 2)
        self.assertEqual([r['chunk_id'] for r, _ in hits], ['2', '3'])

    def test_unknown_and_supplied_scope(self):
        self.assertEqual(allowed_jurisdictions('Unknown'), {'Central', 'India'})
        self.assertIn('Karnataka', allowed_jurisdictions('Unknown', 'ಕर्नाटक Karnataka'))
        self.assertNotIn('Maharashtra', allowed_jurisdictions('Karnataka', 'Maharashtra law'))
        self.assertEqual(allowed_jurisdictions('Central', 'Karnataka'), {'Central', 'India'})
        with self.assertRaises(ValueError):
            allowed_jurisdictions('unsupported')

    def test_expected_sources_and_duplicates(self):
        self.assertTrue(source_hits(['a', 'a', 'a'], ['a', 'b'], 3))
        self.assertFalse(source_hits(['a', 'a'], ['a', 'b'], 3, require_all=True))
        self.assertTrue(source_hits(['a', 'b'], ['a', 'b'], 3, require_all=True))
        self.assertFalse(source_hits(['a'], [], 5))

    def test_empty_scope(self):
        index = faiss.IndexFlatIP(2)
        self.assertEqual(scoped_search(index, [], np.array([1, 0]), {'Central'}), [])

    def test_long_text_preserved_in_windows(self):
        text = ' '.join(f'word{i}' for i in range(1000))
        record = dict(text=text, chunk_id='synthetic', title='Official title', section='4')
        config = dict(context_token_limit=64, passage_prefix='passage: ', max_seq_length=512, body_window_tokens=440)
        windows, weights = embedding_windows(record, WordTokenizer(), config)
        self.assertGreater(len(windows), 1)
        self.assertEqual(sum(weights), 1000)
        self.assertEqual(''.join(w.split('Text: ', 1)[1] for w in windows), text)
        self.assertTrue(all(len(w.split()) <= 512 for w in windows))

    def test_cache_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / 'payload'
            payload.write_text('original')
            (root / 'manifest.json').write_text(json.dumps({'fingerprint': 'abc', 'artifacts': {'payload': digest(payload)}}))
            self.assertIsNotNone(valid_manifest(root, 'abc'))
            self.assertIsNone(valid_manifest(root, 'other'))
            payload.write_text('corrupt')
            self.assertIsNone(valid_manifest(root, 'abc'))

    def test_active_only_and_reuse_without_embedding(self):
        class FakeModel:
            tokenizer = WordTokenizer()

            def encode(self, texts, **kwargs):
                return np.array([[1., 0.]] * len(texts), dtype='float32')

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            documents, sources = root / 'docs.jsonl', root / 'sources.csv'
            sources.write_text('source_id,jurisdiction\ns,Central\n')
            base = dict(source_id='s', jurisdiction='Central', title='Title', text='Official complete provision text.')
            documents.write_text('\n'.join(json.dumps(dict(base, chunk_id=str(i), retrieval_status=status))
                                             for i, status in enumerate(['ACTIVE', 'REFERENCE_ONLY', 'REVIEW'])))
            config = dict(embedding_dimension=2, context_token_limit=64, passage_prefix='passage: ',
                          max_seq_length=512, body_window_tokens=440, batch_size=2, model_name='synthetic')
            inputs = {'documents': digest(documents), 'sources': digest(sources)}
            with patch.object(builder, 'DOCUMENTS', documents), patch.object(builder, 'SOURCES', sources), \
                 patch.object(builder, 'fingerprint', return_value=('synthetic', inputs)), \
                 patch.object(builder, 'load_model', return_value=FakeModel()) as loader, redirect_stdout(io.StringIO()):
                first = builder.build(config, folder=root / 'index')
                second = builder.build(config, folder=root / 'index')
                self.assertEqual(loader.call_count, 1)
            self.assertEqual(first['counts']['active_records_indexed'], 1)
            self.assertEqual(second['counts']['records_excluded'], 2)
            rows = [json.loads(line) for line in (root / 'index/metadata.jsonl').read_text().splitlines()]
            self.assertEqual([r['chunk_id'] for r in rows], ['0'])
            self.assertNotIn('text', rows[0])


if __name__ == '__main__':
    unittest.main()
