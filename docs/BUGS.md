# Known Bugs

## UTF-8 Surrogate Encoding Error in Query

**Date Reported:** 2026-04-07

**Error Message:**
```
'utf-8' codec can't encode character '\udce8' in position 32: surrogates not allowed
```

**Trigger:**
- Command: `/query animal-nutrition-breeding "小猪 腹泻"`
- Environment: Interactive chat mode (`run_interactive()` in `main.py`)

**Root Cause:**
A lone surrogate character (U+DC88 high surrogate) exists in the query string or in one of the retrieved document texts. Python's UTF-8 encoder cannot encode surrogate characters, which are only valid in UTF-16 encoding.

**Likely Locations:**
1. `kb/services.py` - `_query_across_kbs()` at line ~1320 - prompt construction with user query
2. `src/llamaindex_study/reranker.py` - `SiliconFlowReranker._postprocess_nodes()` - sends query/documents to API
3. `src/llamaindex_study/embedding_service.py` - `OllamaEmbeddingService._embed_single()` - sends text to Ollama

**Debugging Steps:**
1. Add `traceback.print_exc()` to the exception handler in `main.py:235-236`
2. Check logs in `~/.llamaindex/logs/`
3. Verify if the error occurs in reranker or embedding service

**Workaround:**
Disable reranker temporarily to isolate the issue.

**Status:** Fixed (2026-04-08) - Added `_remove_surrogates()` sanitization in:
- `src/llamaindex_study/reranker.py` - `_postprocess_nodes()`, `rerank()`, `EmbeddingSimilarityReranker._get_embedding()`
- `src/llamaindex_study/embedding_service.py` - `OllamaEmbeddingService._embed_single()`, `SiliconFlowEmbedding.get_text_embeddings()`
- `kb/keyword_extractor.py` - `_extract_with_llm()`
- `kb/topic_analyzer.py` - `_llm_extract_topics()`
