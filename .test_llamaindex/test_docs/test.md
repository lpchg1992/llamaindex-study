# Test Document for LlamaIndex Upgrade

This is a test document created for verifying the LlamaIndex upgrade from v0.10 to v0.14.

## Section 1: Introduction

LlamaIndex is a powerful data framework for building LLM applications. It provides tools for data ingestion, parsing, indexing, retrieval, and agent creation.

## Section 2: Key Features

- **RAG (Retrieval-Augmented Generation)**: Combine LLMs with your data
- **Vector Search**: Semantic search capabilities
- **Document Processing**: Load various document formats
- **Agent Framework**: Build AI agents

## Section 3: Test Content

This document contains sample content for testing:
- Python programming
- Machine learning concepts
- RAG system architecture
- Vector database integration

## Section 4: Code Example

```python
from llama_index.core import VectorStoreIndex

# Create index from documents
index = VectorStoreIndex.from_documents(documents)

# Query the index
query_engine = index.as_query_engine()
response = query_engine.query("What is LlamaIndex?")
```

## Section 5: Conclusion

This test document is used to verify that the LlamaIndex upgrade works correctly.
