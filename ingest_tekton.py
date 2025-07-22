import os
import time
import logging
from pathlib import Path
from typing import List, Dict
from datetime import datetime
from llama_stack_client import LlamaStackClient
import uuid
import hashlib

class TektonIngestor:
    def __init__(self, base_url: str = "http://localhost:8321", log_level: str = "INFO", recreate_db: bool = False):
        """
        Initialize TektonIngestor
        
        Args:
            base_url: Base URL for LlamaStack client (default: http://localhost:8321)
            log_level: Logging level (default: INFO)
            recreate_db: Whether to recreate vector DB if it exists (default: False)
        """
        self._setup_logging(log_level)
        self.logger = logging.getLogger("TektonIngestor")
        self.client = LlamaStackClient(base_url=base_url)
        self.logger.info(f"Initialized LlamaStack client with base URL: {base_url}")
        self.vector_db_id = "tekton_docs_vector_db"
        self.recreate_db = recreate_db
        
        # Track ingested documents for debugging
        self.ingested_doc_ids = set()
        
        self._init_metrics()
        
        # Configuration
        self.supported_formats = {'.md', '.txt', '.pdf', '.html', '.docx', '.pptx', '.csv', '.json', '.yaml', '.yml'}
        self.chunk_size = 256  # tokens
        self.embedding_model = "text-embedding-004"
        self.embedding_dimension = 384
        self.max_batch_size = 50  # Reduced from 100 to be safe with VertexAI limits

    def _setup_logging(self, log_level: str):
        """Configure logging with file and console output"""
        # Convert string to logging level
        numeric_level = getattr(logging, log_level.upper(), logging.INFO)
        
        logging.basicConfig(
            level=numeric_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('tekton_ingestion.log'),
                logging.StreamHandler()
            ],
            force=True  # Force reconfiguration
        )

    def _init_metrics(self):
        """Initialize ingestion metrics tracking"""
        self.metrics = {
            'start_time': datetime.now(),
            'files_processed': 0,
            'files_skipped': 0,
            'files_failed': 0,
            'last_success': None,
            'files_found': 0
        }

    def _log_metrics(self):
        """Log summary metrics"""
        duration = (datetime.now() - self.metrics['start_time']).total_seconds()
        self.logger.info(
            f"Ingestion Metrics: "
            f"Found={self.metrics['files_found']} "
            f"Processed={self.metrics['files_processed']} "
            f"Skipped={self.metrics['files_skipped']} "
            f"Failed={self.metrics['files_failed']} "
            f"Duration={duration:.2f}s"
        )

    def _validate_directory(self, doc_dir: Path) -> bool:
        """Verify the directory exists and is accessible"""
        if not doc_dir.exists():
            self.logger.error(f"Directory does not exist: {doc_dir}")
            return False
        if not doc_dir.is_dir():
            self.logger.error(f"Path is not a directory: {doc_dir}")
            return False
        return True

    def load_documents(self, doc_dir: Path) -> List[Dict]:
        """Load and prepare documents for ingestion"""
        documents = []
        
        if not self._validate_directory(doc_dir):
            return documents

        self.logger.info(f"Scanning directory: {doc_dir}")
        
        # Recursively find all files in directory
        for file in doc_dir.rglob('*'):
            try:
                if file.is_dir():
                    continue
                    
                self.metrics['files_found'] += 1
                self.logger.debug(f"Found file: {file}")

                if file.suffix.lower() not in self.supported_formats:
                    self.logger.debug(f"Skipping unsupported format: {file.name}")
                    self.metrics['files_skipped'] += 1
                    continue

                with open(file, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Generate deterministic document ID
                doc_id = self._generate_document_id(file, content)
                
                documents.append({
                    "document_id": doc_id,
                    "content": content,
                    "metadata": {
                        "source": str(file),
                        "file_name": file.name,
                        "file_size": os.path.getsize(file),
                        "modified_at": int(os.path.getmtime(file)),
                        "uploaded_at": int(time.time()),
                        "content_hash": hashlib.md5(content.encode('utf-8')).hexdigest()
                    }
                })
                self.logger.info(f"Loaded document: {file.name} (ID: {doc_id})")
                
            except UnicodeDecodeError:
                self.logger.warning(f"Encoding issue with file {file}, trying binary read")
                try:
                    with open(file, "rb") as f:
                        content = f.read().decode('utf-8', errors='replace')
                    
                    # Generate deterministic document ID
                    doc_id = self._generate_document_id(file, content)
                    
                    documents.append({
                        "document_id": doc_id,
                        "content": content,
                        "metadata": {
                            "source": str(file),
                            "file_name": file.name,
                            "file_size": os.path.getsize(file),
                            "modified_at": int(os.path.getmtime(file)),
                            "uploaded_at": int(time.time()),
                            "content_hash": hashlib.md5(content.encode('utf-8')).hexdigest(),
                            "encoding": "utf-8-with-replace"
                        }
                    })
                except Exception as e:
                    self.logger.error(f"Failed to read file {file}: {str(e)}")
                    self.metrics['files_failed'] += 1
            except Exception as e:
                self.logger.error(f"Error processing {file.name}: {str(e)}")
                self.metrics['files_failed'] += 1
        
        return documents



    def _generate_document_id(self, file_path: Path, content: str) -> str:
        """
        Generate deterministic document ID based on file path and content hash.
        
        This ensures:
        - Same file with same content = same ID (no duplicates)
        - File content changes = new ID (updates properly)
        - Different files = different IDs (no conflicts)
        
        Format: filename_extension_contenthash
        """
        # Use file path + content hash for deterministic ID
        path_str = str(file_path.relative_to(file_path.anchor) if file_path.is_absolute() else file_path)
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
        return f"{path_str.replace('/', '_').replace('\\', '_')}_{content_hash}"

    def _vector_db_exists(self) -> bool:
        """Check if vector DB already exists"""
        try:
            existing_dbs = self.client.vector_dbs.list()
            return any(db.identifier == self.vector_db_id for db in existing_dbs)
        except Exception as e:
            self.logger.warning(f"Error checking existing vector DBs: {str(e)}")
            return False

    def setup_vector_db(self, recreate: bool = False):
        """Initialize vector DB only if needed"""
        self.recreate_db = recreate
        
        if self._vector_db_exists() and not recreate:
            self.logger.info(f"Vector DB '{self.vector_db_id}' already exists - skipping creation")
            return

        try:
            provider_id = os.environ.get('VECTOR_STORE', 'faiss')
            action = "Recreating" if recreate else "Creating"
            self.logger.info(f"{action} vector DB with provider: {provider_id}")
            
            if recreate:
                self.client.vector_dbs.unregister(vector_db_id=self.vector_db_id)

            self.client.vector_dbs.register(
                vector_db_id=self.vector_db_id,
                embedding_model=self.embedding_model,
                embedding_dimension=self.embedding_dimension,
                provider_id=provider_id
            )
            self.logger.info(f"Vector DB '{self.vector_db_id}' initialized")
        except Exception as e:
            self.logger.error(f"Vector DB setup failed: {str(e)}")
            raise

    def ingest_documents(self, documents: List[Dict]):
        """
        Ingest documents using the RAG tool with proper batch handling.
        
        Uses deterministic document IDs to handle updates:
        - Same content = same ID (vector DB will deduplicate)
        - Changed content = new ID (old version replaced)
        """
        if not documents:
            self.logger.warning("No documents to ingest")
            return

        try:
            total_docs = len(documents)
            self.logger.info(f"Starting ingestion of {total_docs} documents in batches of {self.max_batch_size}")
            self.logger.info("Using deterministic IDs - vector DB will handle deduplication")
            
            # Debug: Show all document IDs being processed
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug("Document IDs being processed:")
                for i, doc in enumerate(documents):
                    self.logger.debug(f"  {i+1}. {doc['metadata']['file_name']} -> {doc['document_id']}")
            
            for i in range(0, total_docs, self.max_batch_size):
                batch = documents[i:i + self.max_batch_size]
                batch_num = (i // self.max_batch_size) + 1
                total_batches = (total_docs // self.max_batch_size) + 1
                
                self.logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} docs)")
                
                try:
                    start_time = time.time()
                    self.client.tool_runtime.rag_tool.insert(
                        documents=batch,
                        vector_db_id=self.vector_db_id,
                        chunk_size_in_tokens=self.chunk_size,
                    )
                    processing_time = time.time() - start_time
                    
                    self.metrics['files_processed'] += len(batch)
                    self.metrics['last_success'] = datetime.now()
                    
                    # Track successfully ingested document IDs
                    for doc in batch:
                        self.ingested_doc_ids.add(doc["document_id"])
                    
                    self.logger.debug(f"Session now tracking {len(self.ingested_doc_ids)} successfully ingested documents")
                    
                    self.logger.info(
                        f"Completed batch {batch_num} in {processing_time:.2f}s "
                        f"(Avg: {processing_time/len(batch):.2f}s/doc)"
                    )
                    
                    # Dynamic delay based on processing time
                    delay = min(2.0, processing_time * 0.5)
                    time.sleep(delay)
                    
                except Exception as batch_error:
                    self.logger.error(f"Failed batch {batch_num}: {str(batch_error)}")
                    self.metrics['files_failed'] += len(batch)
                    
                    # Try processing documents individually
                    self._process_documents_individually(batch)
            
            self.logger.info(
                f"Ingestion complete. Success: {self.metrics['files_processed']}/"
                f"{total_docs}, Failed: {self.metrics['files_failed']}"
            )
            
        except Exception as e:
            self.logger.error(f"Document ingestion failed: {str(e)}")
            raise

    def _process_documents_individually(self, documents: List[Dict]):
        """Fallback method to process documents one by one"""
        self.logger.warning("Attempting individual document processing...")
        
        for doc in documents:
            try:
                self.client.tool_runtime.rag_tool.insert(
                    documents=[doc],  # Single document
                    vector_db_id=self.vector_db_id,
                    chunk_size_in_tokens=self.chunk_size,
                )
                self.metrics['files_processed'] += 1
                
                # Track successfully ingested document ID
                self.ingested_doc_ids.add(doc["document_id"])
                
                self.logger.debug(f"Processed individual document: {doc['metadata']['file_name']} -> {doc['document_id']}")
                self.logger.debug(f"Session now tracking {len(self.ingested_doc_ids)} successfully ingested documents")
                time.sleep(0.5)  # Conservative delay between individual docs
            except Exception as e:
                self.metrics['files_failed'] += 1
                self.logger.error(
                    f"Failed to process document {doc['metadata']['file_name']}: "
                    f"{str(e)}"
                )

    def run(self, docs_dir: str):
        """Main execution flow"""
        self.logger.info(f"Starting Tekton documentation ingestion from: {docs_dir}")
        
        try:
            self.setup_vector_db(recreate=self.recreate_db)
            documents = self.load_documents(Path(docs_dir))
            
            if documents:
                self.ingest_documents(documents)
            else:
                self.logger.warning("No valid documents found in the specified directory")
                
                # Diagnostic info
                doc_path = Path(docs_dir)
                self.logger.info(f"Directory contents: {[f.name for f in doc_path.iterdir() if f.is_file()]}")
                self.logger.info(f"Supported formats: {self.supported_formats}")
                
        except Exception as e:
            self.logger.critical(f"Ingestion failed: {str(e)}")
        finally:
            self._log_metrics()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-dir", default="./tekton-docs", help="Directory containing Tekton documents")
    parser.add_argument("--base-url", default="http://localhost:8321", help="Base URL for LlamaStack client")
    parser.add_argument("--recreate-db", action="store_true", help="Recreate vector DB if it exists")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], 
                       help="Logging level")
    args = parser.parse_args()
    
    # Override log level if debug flag is set
    if args.debug:
        args.log_level = "DEBUG"
    
    ingestor = TektonIngestor(base_url=args.base_url, log_level=args.log_level, recreate_db=args.recreate_db)
    ingestor.run(args.docs_dir)
