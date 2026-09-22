# Retrieval baseline

Run from the project root:

```powershell
python -m pip install -r requirements.txt
python scripts/build_retrieval_index.py
python scripts/evaluate_retrieval.py
python -m unittest discover -s scripts -p test_retrieval.py
```

Only ACTIVE records enter the index. REFERENCE_ONLY and REVIEW records are excluded,
including reference parents. The source documents, extraction output and questions
are never edited. No answer-generation model, paid service or reranker is used.

Model selection is in `config.json`: `intfloat/multilingual-e5-small`, 384 dimensions,
pinned model revision, CPU execution. The [model card](https://huggingface.co/intfloat/multilingual-e5-small)
lists English, Hindi, Kannada and Marathi among its supported languages. It is a
practical small multilingual retrieval baseline, not a guarantee of equal language
quality. The supplied questions currently evaluate English queries only.

E5 uses `query: ` and `passage: ` prefixes and normalized vectors. Available official
metadata is added as structural context, limited to 64 tokens and at most one third
of source tokens. Long source texts use non-overlapping embedding windows: normalized
window embeddings are weighted by source token count, averaged, then normalized to
one vector per original chunk. This avoids truncating source text, though averaging
can dilute narrow details in long provisions. No new corpus chunks are created.

`index/index.faiss` stores an exact inner-product FAISS index, `metadata.jsonl` its
ordered mapping (250-character source previews only), and `manifest.json` the model
configuration, package versions, counts and integrity hashes. Rebuilding a valid
index reuses it without loading the model or embedding documents. `--force` rebuilds
intentionally; changed inputs/configuration/code or corrupt artifacts invalidate it.
The manifest is committed last so an interrupted build cannot be reused as valid.

Evaluation uses the supplied jurisdiction, never inferred jurisdiction. Karnataka
and Maharashtra each allow their own state plus Central/India; Central, Multi-State,
India and PMFBY allow Central/India only. Unknown allows Central/India, plus a state
only if explicitly named. A FAISS subset is constructed before ranking. Top-five
cosine results retain duplicate sources and use chunk ID to resolve exact score ties.

Source hits use any expected source by default; a future explicitly multi-source
question can set `require_all_expected_sources: true`. No current question clearly
requires all expected sources. Source hit rates use only answerable questions.
Forbidden-source and jurisdiction rates count violating questions over all questions.
No combined answerable/abstention accuracy is reported.

Abstention candidacy is an intentionally uncalibrated rule fixed before evaluating:
no results or maximum cosine score below 0.70. It never uses expected sources or
should_answer labels. E5 often assigns high scores to weakly relevant material;
similarity cannot prove factual support. Results for unanswerable questions are
reported, not suppressed. Summary fields leave support/general-material assessment
explicitly unverified for manual evidence review. This is not chatbot abstention.
After inspection, `results/abstention_support_review.json` can record evidence-only
assessments and rationales. Evaluation applies them to reporting only when the
question hash, index fingerprint and ordered result chunk IDs all match. They never
affect routing, scores, hit rates, or the abstention-candidate heuristic.

`results/retrieval_results.csv` has one row per returned result, structural metadata,
scores and a maximum 250-character preview. `retrieval_summary.csv` has per-question
checks; `retrieval_metrics.json` has denominators, rates and failed-query diagnostics.
Only failed top-five questions are printed in detail. No source-specific boosts,
question overrides or tuning are applied.

The second stage takes the dense top 15 and adds one highest-scoring chunk from each
allowed source absent from that set. It then selects five items greedily using fixed
cosine semantic similarity 0.58, controlled-topic overlap 0.22,
heading relevance 0.15, and a 0.05 bonus for a source not yet selected. This is a
source-diversity safeguard, not an expected-source rule. The final CSV records each
component and combined rerank score; the FAISS index and embedding model are
unchanged.
