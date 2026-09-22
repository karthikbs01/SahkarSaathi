"""Grounded Groq answer generation over the frozen retrieval/reranker pipeline.

This script does not alter the corpus, questions, FAISS index, model, or reranker.
It uses the existing retrieval functions, sends only retrieved ACTIVE evidence to
Groq, and constructs citations locally.
"""
import argparse
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from typing import Optional
from groq import Groq
from pydantic import BaseModel

from retrieval_common import (DEFAULT_CONFIG, DOCUMENTS, INDEX_DIR, ROOT,
                              allowed_jurisdictions, fingerprint, load_config,
                              load_model, valid_manifest)
from evaluate_retrieval import diverse_candidate_pool, rerank_candidates

ENV_PATH = ROOT / '.env'
TEST_CASES = [
    {'id': 'TEST_LAW', 'question': 'Which law governs cooperative societies in Karnataka?',
     'jurisdiction': 'Karnataka'},
    {'id': 'TEST_PMFBy', 'question': 'What should a farmer do after crop damage under PMFBY?',
     'jurisdiction': 'India'},
    {'id': 'TEST_BYLAWS', 'question': "What does my society's own registered bye-laws say about Rule 12?",
     'jurisdiction': 'Unknown'},
]
TRANSIENT_OPENAI_STATUS = {429, 500, 502, 503, 504}
EVIDENCE_CHAR_BUDGET = 12000


class RagResponse(BaseModel):
    answer: str
    abstained: bool
    abstention_reason: Optional[str] = None
    used_evidence_ids: list[str]


def load_dotenv(path=ENV_PATH):
    values = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
        os.environ.setdefault(key.strip(), value)
    return values


def safe_response(answer='', reason=None, used=None):
    return {'answer': answer, 'abstained': bool(reason),
            'abstention_reason': reason, 'used_chunk_ids': used or [], 'citations': []}


def precheck(question, jurisdiction):
    text = question.casefold()
    if re.search(r"(?:my|our|the)\s+(?:society|cooperative).{0,80}(?:own|registered|society-specific).{0,40}bye[- ]?laws?", text):
        return 'SOCIETY_SPECIFIC_BYLAWS_NOT_IN_CORPUS'
    if re.search(r"(?:current|present)\s+(?:president|secretary|chairperson|officer)|who is the current", text):
        return 'CURRENT_SOCIETY_SPECIFIC_FACT_NOT_IN_CORPUS'
    if re.search(r'\b(?:guarantee|predict|assure)\b|decided?\s+in\s+my\s+favo[u]?r', text):
        return 'CANNOT_GUARANTEE_OR_PREDICT_LEGAL_OUTCOME'
    if (str(jurisdiction).casefold() == 'unknown'
            and re.search(r'\b(?:law|act|rule|section|membership|registered|legal)\b', text)
            and not re.search(r'\b(?:karnataka|maharashtra|central|india|multi[- ]state)\b', text)):
        return 'UNKNOWN_JURISDICTION_FOR_STATE_DEPENDENT_LEGAL_QUESTION'
    return None


def load_active_records():
    records = {}
    with DOCUMENTS.open(encoding='utf-8') as stream:
        for line in stream:
            record = json.loads(line)
            if record.get('retrieval_status') == 'ACTIVE':
                records[record['chunk_id']] = record
    return records


def retrieve(question, jurisdiction, config, model, index, metadata):
    allowed = allowed_jurisdictions(jurisdiction, question)
    query = config['query_prefix'] + question
    if len(model.tokenizer.encode(query)) > config['max_seq_length']:
        raise ValueError('QUESTION_EXCEEDS_ENCODER_LIMIT')
    vector = model.encode([query], normalize_embeddings=True, show_progress_bar=False,
                          convert_to_numpy=True)[0]
    pool = diverse_candidate_pool(index, metadata, vector, allowed)
    return rerank_candidates(pool, question)[:config['top_k']]


def evidence_block(hits, records):
    blocks = []
    for position, (record, score, rerank) in enumerate(hits, 1):
        full = records.get(record['chunk_id'])
        if not full:
            continue
        metadata = {key: full.get(key) for key in (
            'source_id', 'title', 'jurisdiction', 'document_type',
            'section', 'subsection', 'rule', 'subrule', 'clause', 'heading',
            'topics', 'page_start', 'page_end')}
        metadata['evidence_id'] = f'E{position}'
        metadata['_internal_chunk_id'] = record['chunk_id']
        blocks.append({'metadata': metadata, 'text': full['text']})
    return blocks


def _model_evidence_item(item):
    clean = dict(item)
    clean['metadata'] = {k: v for k, v in item['metadata'].items()
                         if not k.startswith('_')}
    clean.pop('_packed_truncated', None)
    return clean


def _safe_prefix(text, limit):
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    boundary = max(prefix.rfind('. '), prefix.rfind('! '), prefix.rfind('? '),
                   prefix.rfind('.\n'), prefix.rfind('!\n'), prefix.rfind('?\n'))
    if boundary > 0:
        return prefix[:boundary + 1]
    return prefix.rsplit(' ', 1)[0]


def pack_evidence(evidence, question, jurisdiction, budget=EVIDENCE_CHAR_BUDGET):
    """Keep ranked evidence intact until a conservative request budget is reached."""
    packed = []
    packed_chars = 0
    skipped = []
    for item in evidence:
        candidate_chars = len(json.dumps(_model_evidence_item(item), ensure_ascii=False))
        if packed_chars + candidate_chars <= budget:
            packed.append(item)
            packed_chars += candidate_chars
            continue
        if not packed:
            truncated = dict(item)
            truncated['metadata'] = dict(item['metadata'])
            overhead = candidate_chars - len(item['text'])
            truncated['text'] = _safe_prefix(item['text'], max(1, budget - overhead))
            truncated['_packed_truncated'] = True
            packed.append(truncated)
            packed_chars = len(json.dumps(_model_evidence_item(truncated), ensure_ascii=False))
            break
        skipped.append({
            'chunk_id': item['metadata']['_internal_chunk_id'],
            'skipped_for_budget': True,
        })
    # Evidence IDs describe only the records actually supplied to the model.
    # Reassign them after packing so skipped candidates cannot leave ID gaps.
    packed_with_ids = []
    for position, item in enumerate(packed, 1):
        packed_item = dict(item)
        packed_item['metadata'] = dict(item['metadata'])
        packed_item['metadata']['evidence_id'] = f'E{position}'
        packed_with_ids.append(packed_item)
    packed = packed_with_ids
    prompt_chars = len(prompt_for(question, jurisdiction, [_model_evidence_item(item) for item in packed]))
    return packed, {
        'retrieved_chunk_count': len(evidence),
        'packed_chunk_count': len(packed),
        'packed_evidence_char_count': packed_chars,
        'estimated_request_token_count': (prompt_chars + 3) // 4,
        'skipped_chunks': skipped,
    }


def prompt_for(question, jurisdiction, evidence):
    return '''You are a grounded cooperative-law assistant for farmers and cooperative members.
Answer ONLY from the supplied evidence. If the evidence does not directly support an answer,
abstain. Do not infer or invent sections, rules, forms, deadlines, premiums, eligibility,
authorities, procedures, or contact details. Do not answer society-specific bye-laws, current
society-specific facts, unknown-jurisdiction state-law questions, or requests to guarantee or
predict legal outcomes. When the user's jurisdiction has already been resolved and evidence
from that jurisdiction is available, do not abstain merely because the question mentions
another jurisdiction. Answer using only the allowed jurisdiction evidence. You may explain
that the other jurisdiction's sources were not used for this answer. Do not make broader claims
about whether another state's law could ever apply in other circumstances. Keep the answer concise and simple.

Return only a JSON object matching the supplied structured response schema with keys
answer, abstained, abstention_reason, and used_evidence_ids. Use an empty answer and a
short abstention_reason when evidence is insufficient. Do not return markdown.

Question jurisdiction: ''' + str(jurisdiction) + '''
Question: ''' + question + '''
Evidence records (the metadata labels are source context; quote or rely only on their text):
''' + json.dumps(evidence, ensure_ascii=False)


def parse_structured_output(text):
    text = (text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.I)
        text = re.sub(r'\s*```$', '', text)
    data = json.loads(text)
    parsed = RagResponse.model_validate(data)
    result = parsed.model_dump()
    result['citations'] = []
    return result


def groq_call(question, jurisdiction, evidence, api_key, model_name, timeout=45, max_attempts=3):
    client = Groq(api_key=api_key, timeout=timeout)
    model_evidence = [_model_evidence_item(item) for item in evidence]
    try:
      for attempt in range(max_attempts):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{'role': 'user', 'content': prompt_for(question, jurisdiction, model_evidence)}],
                temperature=0,
                response_format={'type': 'json_object'})
            return parse_structured_output(response.choices[0].message.content), None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None, 'OPENAI_MALFORMED_RESPONSE'
        except TimeoutError:
            return None, 'OPENAI_TIMEOUT_OR_NETWORK_ERROR'
        except Exception as error:
            status = getattr(error, 'status_code', None) or getattr(error, 'code', None)
            try:
                status_code = int(status)
            except (TypeError, ValueError):
                status_code = None
            if status_code in TRANSIENT_OPENAI_STATUS and attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            return None, 'GROQ_HTTP_' + str(status_code) if status_code else 'GROQ_API_ERROR'
    finally:
        client.close()


def validate_and_cite(response, evidence, records):
    supplied = {item['metadata']['_internal_chunk_id'] for item in evidence}
    used = response['used_chunk_ids']
    failures = [f'UNSUPPLIED_USED_CHUNK:{cid}' for cid in used if cid not in supplied]
    if not response['abstained'] and not used:
        failures.append('NON_ABSTAINED_WITHOUT_EVIDENCE')
    citations = []
    for cid in used:
        if cid in supplied and cid in records:
            record = records[cid]
            citations.append({key: record.get(key) for key in (
                'chunk_id', 'source_id', 'title', 'section', 'subsection', 'rule',
                'clause', 'heading', 'page_start', 'page_end', 'source_url')})
    warnings = []
    def norm(value):
        value = unicodedata.normalize('NFKC', str(value or ''))
        value = ''.join(' ' if (ch.isspace() or unicodedata.category(ch) == 'Zs') else ch for ch in value)
        return re.sub(r'\s+', ' ', value).strip().casefold()
    evidence_parts = []
    for item in evidence:
        evidence_parts.append(item.get('text', ''))
        evidence_parts.extend(v for k, v in item.get('metadata', {}).items() if k != '_internal_chunk_id')
    evidence_text = norm(' '.join(str(x) for x in evidence_parts))
    if not response['abstained']:
        for match in re.finditer(r'\b(?:section|rule|form)\s+[a-z0-9]+(?:-[a-z0-9]+)?\b', norm(response['answer'])):
            phrase = match.group(0)
            if phrase not in evidence_text:
                warnings.append('CLAIM_NOT_LOCATED_IN_EVIDENCE:' + phrase)
    return citations, failures, warnings


def answer_case(case, config, model, index, metadata, records, api_key, model_name, base_url):
    reason = precheck(case['question'], case['jurisdiction'])
    if reason:
        response = safe_response(reason=reason)
        citations, failures, warnings = [], [], []
        return {'question_id': case['id'], 'response': response, 'citations': citations,
                'citation_validation_failures': failures, 'unsupported_claim_warnings': warnings,
                'primary_provider_result': 'NOT_CALLED', 'fallback_used': False, 'final_provider': 'precheck'}
    try:
        hits = retrieve(case['question'], case['jurisdiction'], config, model, index, metadata)
        evidence = evidence_block(hits, records)
    except Exception as error:
        response = safe_response(reason='RETRIEVAL_ERROR')
        return {'question_id': case['id'], 'response': response, 'citations': [],
                'citation_validation_failures': [type(error).__name__], 'unsupported_claim_warnings': [],
                'primary_provider_result': 'NOT_CALLED', 'fallback_used': False, 'final_provider': 'precheck'}
    packed_evidence, packing_metrics = pack_evidence(evidence, case['question'], case['jurisdiction'])
    response, error = groq_call(case['question'], case['jurisdiction'], packed_evidence, api_key, model_name)
    primary_result = 'PASS' if response is not None else error
    fallback_used = False
    final_provider = 'groq'
    if error:
        response = safe_response(reason=error)
    else:
        evidence_by_id = {item['metadata']['evidence_id']: item for item in packed_evidence}
        evidence_ids = response.get('used_evidence_ids', [])
        response['used_evidence_ids'] = evidence_ids
        invalid = [eid for eid in evidence_ids if eid not in evidence_by_id]
        if invalid:
            response = safe_response(reason='CITATION_VALIDATION_FAILED')
            response['used_evidence_ids'] = evidence_ids
        else:
            response['used_chunk_ids'] = [evidence_by_id[eid]['metadata']['_internal_chunk_id']
                                          for eid in evidence_ids]
    citations, failures, warnings = validate_and_cite(response, packed_evidence, records)
    if failures:
        response = safe_response(reason='CITATION_VALIDATION_FAILED')
        citations = []
    response['citations'] = citations
    return {'question_id': case['id'], 'response': response, 'citations': citations,
            'citation_validation_failures': failures, 'unsupported_claim_warnings': warnings,
            'primary_provider_result': primary_result, 'fallback_used': fallback_used,
            'packing_metrics': packing_metrics,
            'final_provider': final_provider}


def run(cases=TEST_CASES, config_path=DEFAULT_CONFIG):
    load_dotenv()
    api_key = os.getenv('GROQ_API_KEY')
    model_name = os.getenv('GROQ_MODEL')
    if not api_key or not model_name:
        raise RuntimeError('GROQ_CONFIGURATION_MISSING')
    import faiss
    config = load_config(config_path)
    signature, _ = fingerprint(config)
    if not valid_manifest(INDEX_DIR, signature):
        raise RuntimeError('FROZEN_INDEX_INVALID')
    index = faiss.read_index(str(INDEX_DIR / 'index.faiss'))
    metadata = [json.loads(line) for line in (INDEX_DIR / 'metadata.jsonl').open(encoding='utf-8')]
    records = load_active_records()
    model = load_model(config)
    results = [answer_case(case, config, model, index, metadata, records, api_key, model_name, None) for case in cases]
    return model_name, results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-three', action='store_true')
    args = parser.parse_args()
    model_name, results = run(TEST_CASES if args.test_three else TEST_CASES[:1])
    print(json.dumps({'model': model_name, 'results': results}, ensure_ascii=False, indent=2))
