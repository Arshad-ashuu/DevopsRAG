import os
import time
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# ── Config ────────────────────────────────────────────────────────────────────
DOCS_DIR         = "docs"
VECTOR_STORE_DIR = "vector_store"
CHUNK_SIZE       = 500
CHUNK_OVERLAP    = 100
# UPDATED: 'text-embedding-004' is deprecated. Use 'gemini-embedding-001'
EMBED_MODEL      = "models/gemini-embedding-001" 

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    raise ValueError("Set the GEMINI_API_KEY environment variable first.")

# ── Load & split docs ─────────────────────────────────────────────────────────
print("📂 Loading docs …")
if not os.path.exists(DOCS_DIR):
    os.makedirs(DOCS_DIR)
    print(f"⚠️ Created '{DOCS_DIR}' directory. Please add .txt files and rerun.")
    exit()

loader = DirectoryLoader(
    DOCS_DIR,
    glob="**/*.txt",
    loader_cls=TextLoader,
    loader_kwargs={"encoding": "utf-8"},
    show_progress=True,
)
raw_docs = loader.load()

if not raw_docs:
    print("❌ No documents found in the 'docs' folder.")
    exit()

print(f"   Loaded {len(raw_docs)} file(s)")

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
)
chunks = splitter.split_documents(raw_docs)
print(f"   Split into {len(chunks)} chunks\n")

# ── Embed & build LangChain FAISS store ───────────────────────────────────────
print(f"🔢 Embedding with {EMBED_MODEL} (Free Tier mode) …")
embeddings = GoogleGenerativeAIEmbeddings(
    model=EMBED_MODEL,
    google_api_key=GEMINI_API_KEY,
    task_type="retrieval_document",
)

# Free Tier Fix: Process in small batches to avoid 429 Rate Limit errors
BATCH_SIZE = 5  # Reduced for higher stability on Free Tier
vectorstore = None

for i in range(0, len(chunks), BATCH_SIZE):
    batch = chunks[i : i + BATCH_SIZE]
    print(f"   Processing chunks {i} to {min(i + BATCH_SIZE, len(chunks))}...")
    
    try:
        if vectorstore is None:
            vectorstore = FAISS.from_documents(batch, embeddings)
        else:
            vectorstore.add_documents(batch)
    except Exception as e:
        print(f"❌ Error at batch {i}: {e}")
        break
    
    # Pause to stay under Free Tier Requests Per Minute (RPM) limits
    time.sleep(3) 

# ── Persist ───────────────────────────────────────────────────────────────────
if vectorstore:
    os.makedirs(VECTOR_STORE_DIR, exist_ok=True)
    vectorstore.save_local(VECTOR_STORE_DIR)
    print(f"\n✅ Vector store saved to '{VECTOR_STORE_DIR}/'")
    print(f"   Total vectors indexed: {vectorstore.index.ntotal}")
