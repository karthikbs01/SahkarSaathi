import csv, json, os, time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from generate_rag_answer import (load_dotenv, load_active_records, load_config, retrieve,
    evidence_block, precheck, groq_call, validate_and_cite, TEST_CASES)
from retrieval_common import DEFAULT_CONFIG, DOCUMENTS, INDEX_DIR, fingerprint, load_model, valid_manifest, allowed_jurisdictions

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'rag' / 'results'
CSV_PATH, JSON_PATH = OUT / 'rag_evaluation.csv', OUT / 'rag_metrics.json'

def load_questions():
    all_q=[]
    for name in ('questions.json','holdout_questions.json'):
        all_q.extend(json.loads((ROOT/'data'/'tests'/name).read_text(encoding='utf-8')))
    return all_q

def main():
    OUT.mkdir(parents=True, exist_ok=True); load_dotenv()
    key, model_name = os.getenv('GROQ_API_KEY'), os.getenv('GROQ_MODEL')
    config=load_config(DEFAULT_CONFIG); sig,_=fingerprint(config)
    if not valid_manifest(INDEX_DIR,sig): raise RuntimeError('FROZEN_INDEX_INVALID')
    import faiss
    index=faiss.read_index(str(INDEX_DIR/'index.faiss'))
    metadata=[json.loads(x) for x in (INDEX_DIR/'metadata.jsonl').open(encoding='utf-8')]
    model=load_model(config); records=load_active_records(); questions=load_questions()
    fields=['question_id','answered','abstained','expected_should_answer','behavior_correct','used_evidence_ids','mapped_chunk_ids','cited_source_ids','citation_validation_pass','unsupported_claim_warning','jurisdiction_violation','forbidden_source_leakage','api_status','retry_count','failure_reason','answer_preview']
    rows=[]
    for i,q in enumerate(questions):
        reason=precheck(q['question'],q['jurisdiction']); response=None; evidence=[]; failures=[]; warnings=[]; retries=0; status='NOT_CALLED'; failure=''
        if reason:
            response={'answer':'','abstained':True,'abstention_reason':reason,'used_chunk_ids':[],'used_evidence_ids':[],'citations':[]}; status='NOT_CALLED'
        else:
            try:
                hits=retrieve(q['question'],q['jurisdiction'],config,model,index,metadata); evidence=evidence_block(hits,records)
                while True:
                    response,error=groq_call(q['question'],q['jurisdiction'],evidence,key,model_name,max_attempts=1)
                    status='PASS' if response is not None else error
                    if response is not None: break
                    if retries>=2: failure=error; response={'answer':'','abstained':True,'abstention_reason':error,'used_chunk_ids':[],'used_evidence_ids':[],'citations':[]}; break
                    if error and ('HTTP_429' in error or any(f'HTTP_{n}' in error for n in (500,502,503,504))):
                        time.sleep(5 if retries==0 else 10); retries+=1; continue
                    failure=error; response={'answer':'','abstained':True,'abstention_reason':error,'used_chunk_ids':[],'used_evidence_ids':[],'citations':[]}; break
                if response.get('used_evidence_ids') is not None:
                    byid={x['metadata']['evidence_id']:x for x in evidence}; eids=response.get('used_evidence_ids',[])
                    if any(x not in byid for x in eids):
                        failures=['UNSUPPLIED_EVIDENCE_ID']; response['used_chunk_ids']=[]
                    else: response['used_chunk_ids']=[byid[x]['metadata']['_internal_chunk_id'] for x in eids]
                citations,failures,warnings=validate_and_cite(response,evidence,records)
                response['citations']=citations
            except Exception as e:
                failure=type(e).__name__; status='RETRIEVAL_ERROR'; response={'answer':'','abstained':True,'abstention_reason':failure,'used_chunk_ids':[],'used_evidence_ids':[],'citations':[]}
        cited=sorted({x.get('source_id') for x in response.get('citations',[]) if x.get('source_id')})
        expected=q.get('expected_source_ids',[]); forbidden=q.get('forbidden_source_ids',[])
        allowed=allowed_jurisdictions(q['jurisdiction'],q['question'])
        juris=any((records.get(cid,{}).get('jurisdiction') not in allowed) for cid in response.get('used_chunk_ids',[]))
        leak=bool(set(cited)&set(forbidden))
        behavior=bool(response.get('abstained')) == (not q['should_answer'])
        bad=not behavior or bool(failures or warnings or juris or leak or failure)
        rows.append({'question_id':q['id'],'answered':not response.get('abstained',True),'abstained':bool(response.get('abstained')),'expected_should_answer':q['should_answer'],'behavior_correct':behavior,'used_evidence_ids':json.dumps(response.get('used_evidence_ids',[])),'mapped_chunk_ids':json.dumps(response.get('used_chunk_ids',[])),'cited_source_ids':json.dumps(cited),'citation_validation_pass':not bool(failures),'unsupported_claim_warning':json.dumps(warnings),'jurisdiction_violation':juris,'forbidden_source_leakage':leak,'api_status':status,'retry_count':retries,'failure_reason':failure or (';'.join(failures) if failures else ''),'answer_preview':response.get('answer','')[:150]})
        with CSV_PATH.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
        time.sleep(3 if i < len(questions)-1 else 0)
    metrics={'total_questions':len(rows),'answerable_questions':sum(r['expected_should_answer'] for r in rows),'abstention_questions':sum(not r['expected_should_answer'] for r in rows),'correct_behavior_count':sum(r['behavior_correct'] for r in rows),'correct_behavior_rate':sum(r['behavior_correct'] for r in rows)/len(rows),'citation_validation_failures':sum(not r['citation_validation_pass'] for r in rows),'unsupported_claim_warnings':sum(bool(json.loads(r['unsupported_claim_warning'])) for r in rows),'jurisdiction_violations':sum(r['jurisdiction_violation'] for r in rows),'forbidden_source_leakage':sum(r['forbidden_source_leakage'] for r in rows),'api_failures_after_retries':sum(bool(r['failure_reason'] and r['api_status']!='NOT_CALLED') for r in rows),'failed_question_ids':[r['question_id'] for r in rows if (not r['behavior_correct'] or not r['citation_validation_pass'] or json.loads(r['unsupported_claim_warning']) or r['jurisdiction_violation'] or r['forbidden_source_leakage'] or r['failure_reason'])]}
    JSON_PATH.write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(json.dumps(metrics))
if __name__=='__main__': main()
