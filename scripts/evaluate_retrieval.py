"""Evaluate source-level top-5 retrieval with a deterministic second-stage reranker."""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
import tempfile

from retrieval_common import (DEFAULT_CONFIG, INDEX_DIR, RESULT_DIR, ROOT,
                              allowed_jurisdictions, digest, fingerprint, load_config,
                              load_model, source_hits, valid_manifest)

RESULT_FIELDS = ('question_id question test_jurisdiction should_answer rank chunk_id source_id '
                 'title result_jurisdiction similarity_score expected_source_match forbidden_source_match '
                 'jurisdiction_violation section subsection rule clause heading topics page_start page_end text_preview').split()
RESULT_FIELDS += 'rerank_score topic_overlap heading_relevance source_diversity'.split()
SUMMARY_FIELDS = ('question_id top1_match top3_match top5_match forbidden_source_found jurisdiction_violation '
                  'max_similarity abstention_candidate should_answer result_count result_returned_when_should_not_answer '
                  'allowed_jurisdictions expected_source_policy support_assessment unrelated_or_general_material '
                  'abstention_reason').split()

# These weights are fixed for this baseline and are deliberately independent of
# questions.json. The semantic score remains the largest single signal.
RERANK_WEIGHTS = {'semantic': 0.58, 'topic': 0.22, 'heading': 0.15, 'diversity': 0.05}
RERANK_CANDIDATE_K = 15
PROCEDURAL_BOOST = 0.04
PROCEDURAL_QUERY_RE = re.compile(
    r'\b(?:what should (?:i|we|a)\b|how (?:do|can|should)\b|next step\b|'
    r'where (?:do|can|should)\b|what documents?\b|how to (?:report|claim|complain))', re.I)
PROCEDURAL_TOPICS = {'reporting', 'claim', 'documents', 'timeline', 'grievance', 'complaint'}
TOPIC_TERMS = {
    'membership': ('member', 'membership', 'admission'),
    'registration': ('register', 'registration'),
    'management': ('management', 'governing body', 'board'),
    'governance': ('governance',),
    'elections': ('election', 'voting'),
    'meetings': ('meeting', 'agenda'),
    'loans': ('loan', 'borrowing', 'credit'),
    'deposits': ('deposit',),
    'financial_literacy': ('financial literacy',),
    'pacs': ('pacs',),
    'pacs_services': ('pacs service',),
    'computerization': ('computeriz',),
    'crop_insurance': ('crop insurance',),
    'pmfby': ('pmfby', 'pradhan mantri fasal'),
    'eligibility': ('eligible', 'eligibility'),
    'premium': ('premium',),
    'crop_loss': ('crop loss', 'crop damaged', 'damage to crop'),
    'claim': ('claim',),
    'reporting': ('report', 'reporting'),
    'documents': ('document',),
    'timeline': ('time limit', 'timeline', 'within one month', 'within a period'),
    'grievance': ('grievance', 'complain', 'complaint', 'dispute'),
    'complaint': ('complain', 'complaint'),
    'ombudsman': ('ombudsman', 'complain', 'complaint'),
    'appeal': ('appeal',),
    'form_vi': ('form vi', 'form 6'),
    'form_vii': ('form vii', 'form 7'),
    'registrar': ('registrar',),
    'multistate': ('multi-state', 'multistate', 'more than one state'),
    'state_law': ('state law',),
    'byelaws': ('bye-law', 'byelaw'),
}


def scoped_search(index, metadata, query_vector, allowed, top_k=5):
    """Build an exact FAISS view of eligible vectors BEFORE top-k selection."""
    import faiss
    import numpy as np
    eligible = [i for i, row in enumerate(metadata) if row['jurisdiction'] in allowed]
    if not eligible:
        return []
    subset = faiss.IndexFlatIP(index.d)
    vectors = np.asarray([index.reconstruct(i) for i in eligible], dtype='float32')
    subset.add(vectors)
    # Full eligible ordering enables deterministic chunk-ID tie breaking.
    scores, positions = subset.search(np.asarray(query_vector, dtype='float32').reshape(1, -1), len(eligible))
    ranked = [(metadata[eligible[int(pos)]], float(score)) for pos, score in zip(positions[0], scores[0]) if pos >= 0]
    ranked.sort(key=lambda item: (-item[1], item[0]['chunk_id']))
    return ranked[:top_k]


def diverse_candidate_pool(index, metadata, query_vector, allowed, candidate_k=RERANK_CANDIDATE_K):
    """Return dense top-15 plus one representative for each absent source.

    The expansion is source-blind: it uses only allowed jurisdiction and source
    diversity, never expected sources or question labels.
    """
    import numpy as np
    dense = scoped_search(index, metadata, query_vector, allowed, candidate_k)
    by_id = {r['chunk_id']: (r, score) for r, score in dense}
    represented = {r['source_id'] for r, _ in dense}
    best_by_source = {}
    for i, row in enumerate(metadata):
        if row['jurisdiction'] not in allowed or row['source_id'] in represented:
            continue
        score = float(np.dot(index.reconstruct(i), query_vector))
        current = best_by_source.get(row['source_id'])
        if current is None or (score, row['chunk_id']) > (current[1], current[0]['chunk_id']):
            best_by_source[row['source_id']] = (row, score)
    by_id.update({r['chunk_id']: (r, score) for r, score in best_by_source.values()})
    return sorted(by_id.values(), key=lambda item: (-item[1], item[0]['chunk_id']))


def query_topics(question):
    text = question.casefold()
    return {topic for topic, terms in TOPIC_TERMS.items()
            if any(re.search(r'(?<![a-z])' + re.escape(term) + r'(?![a-z])', text) for term in terms)}


def heading_topics(heading):
    return query_topics(heading or '')


def procedural_query(question):
    return bool(PROCEDURAL_QUERY_RE.search(question))


def rerank_candidates(candidates, question):
    """Rerank without labels; selection rewards a new source at each rank."""
    qtopics = query_topics(question)
    is_procedural = procedural_query(question)
    if not candidates:
        return []
    scored = []
    for record, semantic in candidates:
        topic = len(qtopics & set(record.get('topics') or [])) / max(1, len(qtopics))
        heading = len(qtopics & heading_topics(record.get('heading'))) / max(1, len(qtopics))
        procedural_match = bool(PROCEDURAL_TOPICS & set(record.get('topics') or []))
        procedural_match |= bool(PROCEDURAL_TOPICS & heading_topics(record.get('heading')))
        # Cosine similarity is already normalized; retain its absolute value so
        # a lower-scoring source representative is not forced to zero by pooling.
        semantic_norm = semantic
        scored.append({'record': record, 'semantic': semantic, 'semantic_norm': semantic_norm,
                       'topic': topic, 'heading': heading,
                       'procedural_boost': PROCEDURAL_BOOST if is_procedural and procedural_match else 0.0})
    selected, remaining, source_counts = [], scored, Counter()
    while remaining and len(selected) < 5:
        for item in remaining:
            item['diversity'] = 1.0 if source_counts[item['record']['source_id']] == 0 else 0.0
            item['rerank_score'] = (RERANK_WEIGHTS['semantic'] * item['semantic_norm']
                                    + RERANK_WEIGHTS['topic'] * item['topic']
                                    + RERANK_WEIGHTS['heading'] * item['heading']
                                    + RERANK_WEIGHTS['diversity'] * item['diversity']
                                    + item['procedural_boost'])
        best = max(remaining, key=lambda item: (item['rerank_score'], item['semantic'],
                                                 item['record']['chunk_id']))
        selected.append(best)
        source_counts[best['record']['source_id']] += 1
        remaining.remove(best)
    return [(item['record'], item['semantic'], item) for item in selected]


def evaluate(config, questions_path, folder=INDEX_DIR, output=RESULT_DIR):
    import faiss
    signature, _ = fingerprint(config)
    manifest = valid_manifest(folder, signature)
    if not manifest:
        raise ValueError('Missing/stale/corrupt index: run scripts/build_retrieval_index.py first')
    index = faiss.read_index(str(folder / 'index.faiss'))
    with (folder / 'metadata.jsonl').open(encoding='utf-8') as stream:
        metadata = [json.loads(line) for line in stream]
    if index.ntotal != len(metadata) or index.d != config['embedding_dimension']:
        raise ValueError('Index and metadata mapping mismatch')
    if any(r['retrieval_status'] != 'ACTIVE' for r in metadata):
        raise ValueError('Index contains ineligible records')
    questions = json.loads(questions_path.read_text(encoding='utf-8-sig'))
    review_path = output / 'abstention_support_review.json'
    reviews = {}
    if review_path.exists():
        review_data = json.loads(review_path.read_text(encoding='utf-8'))
        if (review_data.get('questions_sha256') == digest(questions_path)
                and review_data.get('index_fingerprint') == signature):
            reviews = {r['question_id']: r for r in review_data['reviews']}
    ids = set()
    for q in questions:
        if q['id'] in ids or not isinstance(q['should_answer'], bool) or not q['question'].strip():
            raise ValueError('Invalid question input')
        if q['should_answer'] and not q.get('expected_source_ids'):
            raise ValueError('Answerable question has no expected sources')
        ids.add(q['id'])
        allowed_jurisdictions(q['jurisdiction'], q['question'])
    model = load_model(config)
    query_texts = [config['query_prefix'] + q['question'] for q in questions]
    if any(len(model.tokenizer.encode(t)) > config['max_seq_length'] for t in query_texts):
        raise ValueError('Query exceeds encoder limit; refusing silent truncation')
    queries = model.encode(query_texts, batch_size=config['batch_size'], normalize_embeddings=True,
                           show_progress_bar=False, convert_to_numpy=True)
    summaries, results, failures = [], [], []
    for q, vector in zip(questions, queries):
        allowed = allowed_jurisdictions(q['jurisdiction'], q['question'])
        candidate_pool = diverse_candidate_pool(index, metadata, vector, allowed)
        reranked = rerank_candidates(candidate_pool, q['question'])
        hits = [(record, semantic) for record, semantic, _ in reranked]
        expected, forbidden = q.get('expected_source_ids', []), q.get('forbidden_source_ids', [])
        # Optional explicit annotation for future questions needing all sources.
        # Current fixture has no such multi-source requirement.
        require_all = q.get('require_all_expected_sources', False)
        source_ids = [r['source_id'] for r, _ in hits]
        violations = [r['jurisdiction'] not in allowed for r, _ in hits]
        maximum = max((score for _, score in candidate_pool), default=None)
        candidate = maximum is None or maximum < config['abstention_similarity_threshold']
        reason = 'NO_RESULTS' if maximum is None else 'LOW_SIMILARITY' if candidate else 'ABOVE_UNCALIBRATED_THRESHOLD'
        for rank, (r, score) in enumerate(hits, 1):
            result = {key: r.get(key, '') for key in RESULT_FIELDS}
            rerank = reranked[rank - 1][2]
            result.update(question_id=q['id'], question=q['question'], test_jurisdiction=q['jurisdiction'],
                          should_answer=q['should_answer'], rank=rank, result_jurisdiction=r['jurisdiction'],
                          similarity_score=round(score, 8), expected_source_match=r['source_id'] in expected,
                          forbidden_source_match=r['source_id'] in forbidden,
                          jurisdiction_violation=r['jurisdiction'] not in allowed,
                          topics=';'.join(r.get('topics', [])), text_preview=r['text_preview'][:250],
                          rerank_score=round(rerank['rerank_score'], 8), topic_overlap=round(rerank['topic'], 8),
                          heading_relevance=round(rerank['heading'], 8), source_diversity=round(rerank['diversity'], 8))
            results.append(result)
        summary = dict(question_id=q['id'],
                       **{f'top{k}_match': source_hits(source_ids, expected, k, require_all) if q['should_answer'] else None for k in (1, 3, 5)},
                       forbidden_source_found=bool(set(source_ids) & set(forbidden)),
                       jurisdiction_violation=any(violations), max_similarity=round(maximum, 8) if maximum is not None else None,
                       abstention_candidate=candidate, should_answer=q['should_answer'], result_count=len(hits),
                       result_returned_when_should_not_answer=not q['should_answer'] and bool(hits),
                       allowed_jurisdictions=';'.join(sorted(allowed)),
                       expected_source_policy='ALL' if require_all else 'ANY',
                       support_assessment='NOT_AUTOMATICALLY_VERIFIED',
                       unrelated_or_general_material='MANUAL_REVIEW_REQUIRED', abstention_reason=reason)
        # Evidence annotations are applied ONLY to reporting, after retrieval and
        # the label-independent candidacy heuristic. Stale evidence is ignored.
        review = reviews.get(q['id'])
        if (not q['should_answer'] and review
                and review['chunk_ids'] == [r['chunk_id'] for r, _ in hits]):
            summary['support_assessment'] = review['support_assessment']
            summary['unrelated_or_general_material'] = review['unrelated_or_general_material']
        summaries.append(summary)
        if q['should_answer'] and not summary['top5_match']:
            failure = dict(question_id=q['id'], question=q['question'], expected_source_ids=expected,
                           top5_source_ids=source_ids, top5_chunk_ids=[r['chunk_id'] for r, _ in hits],
                           scores=[round(score, 6) for _, score in hits])
            failures.append(failure)
    answerable = [r for r in summaries if r['should_answer']]
    abstentions = [r for r in summaries if not r['should_answer']]
    def rate(n, denominator):
        return n / denominator if denominator else None
    metrics = dict(embedding_model=config['model_name'], embedding_dimension=index.d,
                   active_chunks_indexed=index.ntotal, total_jsonl_records=manifest['counts']['total_jsonl_records'],
                   records_excluded=manifest['counts']['records_excluded'], sources_represented=manifest['source_counts'],
                   **{f'top{k}_source_hit_rate': rate(sum(r[f'top{k}_match'] for r in answerable), len(answerable)) for k in (1, 3, 5)},
                   jurisdiction_violation_rate=rate(sum(r['jurisdiction_violation'] for r in summaries), len(summaries)),
                   forbidden_source_leakage_rate=rate(sum(r['forbidden_source_found'] for r in summaries), len(summaries)),
                   rate_definitions='Source hit rates: answerable questions only. Leakage/violation rates: all tested questions, counted once per question.',
                   answerable_questions_tested=len(answerable), abstention_questions_tested=len(abstentions),
                   abstention_questions_with_results=sum(r['result_count'] > 0 for r in abstentions),
                   abstention_candidates=sum(r['abstention_candidate'] for r in summaries),
                   abstention_policy=config['abstention_policy'],
                   abstention_support_reviewed=sum(r['support_assessment'] != 'NOT_AUTOMATICALLY_VERIFIED' for r in abstentions),
                   support_assessment='No entailment or answerability claim: examine retrieved evidence separately.',
                   questions_sha256=digest(questions_path), index_fingerprint=signature,
                   multi_window_chunks=manifest['counts'].get('multi_window_chunks', 0),
                   failed_top5_question_ids=[r['question_id'] for r in failures], failed_top5_questions=failures)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='evaluation-', dir=output) as temp:
        stage = Path(temp)
        for name, fields, rows in [('retrieval_results.csv', RESULT_FIELDS, results),
                                   ('retrieval_summary.csv', SUMMARY_FIELDS, summaries)]:
            with (stage / name).open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        (stage / 'retrieval_metrics.json').write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding='utf-8')
        for name in ['retrieval_results.csv', 'retrieval_summary.csv', 'retrieval_metrics.json']:
            (stage / name).replace(output / name)
    report = {k: metrics[k] for k in ['embedding_model', 'active_chunks_indexed', 'top1_source_hit_rate',
              'top3_source_hit_rate', 'top5_source_hit_rate', 'jurisdiction_violation_rate',
              'forbidden_source_leakage_rate', 'answerable_questions_tested',
              'abstention_questions_tested', 'failed_top5_question_ids']}
    print(json.dumps(report, indent=2))
    for failure in failures:
        print(json.dumps(failure, ensure_ascii=False))
    return metrics


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--questions', type=Path, default=ROOT / 'data/tests/questions.json')
    args = parser.parse_args()
    evaluate(load_config(args.config), args.questions)
