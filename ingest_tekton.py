import os
import time
from pathlib import Path
from typing import List
from termcolor import cprint
import uuid
from llama_stack_client import LlamaStackClient
from llama_index.core.schema import Document  # Required for wrapping content

# --- Init client and config ---
client = LlamaStackClient(base_url="http://localhost:8321")

VECTOR_DB_ID = "tekton_docs_vector_db"
DOCS_DIR = Path("./tekton_docs")
SUPPORTED_FORMATS = {'.md', '.txt', '.pdf', '.html', '.docx', '.pptx', '.csv', '.json', '.yaml', '.yml'}

# --- Load documents from directory ---
def load_documents_for_rag(doc_dir: Path):
    docs = []
    for file in doc_dir.iterdir():
        if file.suffix.lower() not in SUPPORTED_FORMATS:
            continue
        try:
            with open(file, "r", encoding="utf-8") as f:
                content = f.read()
            docs.append({
                "document_id": str(uuid.uuid4()),
                "content": content,
                "metadata": {
                    "source": str(file),
                    "uploaded_at": int(time.time())
                }
            })
        except Exception as e:
            print(f"Error reading {file.name}: {e}")
    return docs

# --- Ingest documents using rag_tool ---
def ingest_documents_into_rag(client, documents: List[Document], vector_db_id: str):
    try:
        cprint(f"Starting ingestion of {len(documents)} documents into vector DB", "blue")
        
        provider_id = os.environ.get('VECTOR_STORE', 'faiss')

        client.vector_dbs.register(
            vector_db_id=vector_db_id,
            embedding_model="text-embedding-004",
            embedding_dimension=384,
            provider_id=provider_id
        )

        client.tool_runtime.rag_tool.insert(
            documents=documents,
            vector_db_id=vector_db_id,
            chunk_size_in_tokens=256,
        )

        cprint(f"Successfully ingested {len(documents)} documents into '{provider_id}' vector DB.", "green")
    except Exception as e:
        cprint(f"Error ingesting documents: {e}", "red")
        raise

# --- Main ---
if __name__ == "__main__":
    print("📄 Loading Tekton YAML documents...")
    docs = load_documents_for_rag(DOCS_DIR)

    if not docs:
        print("No valid documents found to ingest.")
    else:
        ingest_documents_into_rag(client, docs, VECTOR_DB_ID)
