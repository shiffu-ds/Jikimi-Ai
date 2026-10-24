# RUVR - Roman Urdu Video Retrieval (draft)

- **Queries:** target ~600 from 15+ people (60 % Roman Urdu, 20 % Urdu script, 20 % English),
  each person writing in their own spelling.
- **Relevance:** `qrels.jsonl` - 0 not relevant, 1 relevant, 2 exact; two annotators, disagreements resolved.
- **Lexicon:** `lexicon.tsv` is exported from the parser's lexicon (`scripts/export_lexicon.py`), so the
  benchmark and the product use the same spelling variants.
- **Metrics:** Recall@1/5/10, MRR, per-language breakdown; bootstrap CIs over queries.
- The seed files here are examples only.

## RUVR-sim (available now, for pipeline testing)

Until real footage is annotated, `python -m eval.ruvr_sim` builds a corpus from simulated scenes
run through the real edge pipeline and server index. Ground truth is the *scripted* bike colour and
number of riders; queries cover several Roman Urdu spellings per colour plus Urdu script. It
measures the whole chain (colour from pixels, rider association, parsing, ranking) but on clean
synthetic pixels: it is a regression test, not the benchmark itself. Numbers: `docs/results.md`.
