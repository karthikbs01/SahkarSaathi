"""Shared baseline configuration, scope routing and index integrity checks."""
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'data/retrieval/config.json'
DOCUMENTS = ROOT / 'data/processed/documents.jsonl'
SOURCES = ROOT / 'data/metadata/sources.csv'
INDEX_DIR = ROOT / 'data/retrieval/index'
RESULT_DIR = ROOT / 'data/retrieval/results'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_config(path=DEFAULT_CONFIG):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if config['top_k'] != 5 or not 0 <= config['abstention_similarity_threshold'] <= 1:
        raise ValueError('Baseline requires top_k=5 and a cosine threshold in [0,1]')
    if min(config['batch_size'], config['body_window_tokens'], config['cpu_threads']) < 1:
        raise ValueError('Invalid resource limits')
    return config


def fingerprint(config):
    # Evaluation-only parameters do not invalidate document embeddings.
    settings = {k: v for k, v in config.items() if k not in {
        'top_k', 'abstention_similarity_threshold', 'abstention_policy'}}
    inputs = {'documents': digest(DOCUMENTS), 'sources': digest(SOURCES),
              'builder': digest(Path(__file__).with_name('build_retrieval_index.py')),
              'common': digest(Path(__file__)), 'config': settings}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(), inputs


def allowed_jurisdictions(jurisdiction, question=''):
    """Use supplied routing input; explicit state names only refine Unknown."""
    central = {'Central', 'India'}
    value = (jurisdiction or 'Unknown').strip().casefold()
    if value == 'karnataka':
        return central | {'Karnataka'}
    if value == 'maharashtra':
        return central | {'Maharashtra'}
    if value in {'central', 'multi-state', 'multistate', 'multi state', 'india', 'pmfby', 'central / multi-state', 'india / pmfby'}:
        return central
    if value == 'unknown':
        for state, pattern in [('Karnataka', r'\bkarnataka\b|कर्नाटक|ಕರ್ನಾಟಕ'),
                               ('Maharashtra', r'\bmaharashtra\b|महाराष्ट्र|ಮಹಾರಾಷ್ಟ್ರ')]:
            if re.search(pattern, question, re.I):
                central.add(state)
        return central
    raise ValueError(f'Unsupported routing jurisdiction: {jurisdiction}')


def valid_manifest(folder, signature):
    try:
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['fingerprint'] != signature:
            return None
        for name, expected in manifest['artifacts'].items():
            if digest(folder / name) != expected:
                return None
        return manifest
    except (OSError, KeyError, ValueError):
        return None


def load_model(config):
    os.environ.setdefault('HF_HUB_DISABLE_PROGRESS_BARS', '1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(config['cpu_threads'])
    torch.manual_seed(0)
    model = SentenceTransformer(config['model_name'], revision=config['model_revision'],
                                device=config['device'], trust_remote_code=False)
    model.max_seq_length = config['max_seq_length']
    if model.get_sentence_embedding_dimension() != config['embedding_dimension']:
        raise ValueError('Configured embedding dimension does not match model')
    return model


def source_hits(source_ids, expected, k, require_all=False):
    if not expected:
        return False
    found = set(source_ids[:k])
    return set(expected) <= found if require_all else bool(set(expected) & found)
