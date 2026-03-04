
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI

# ── FIX: 2026 Redirects for LangChain v1.0 ──
from langchain_classic.chains import create_history_aware_retriever, create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
# Ensure you see (venv) in your prompt

# ── Config ────────────────────────────────────────────────────────────────────
VECTOR_STORE_DIR = "vector_store"
EMBED_MODEL      = "models/gemini-embedding-001" 
CHAT_MODEL       = "gemini-2.5-flash"
TOP_K            = 4

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    raise ValueError("Set the GEMINI_API_KEY environment variable first.")

# ── Load Vector Store ─────────────────────────────────────────────────────────
embeddings = GoogleGenerativeAIEmbeddings(
    model=EMBED_MODEL,
    google_api_key=GEMINI_API_KEY,
    task_type="retrieval_query",
)

vectorstore = FAISS.load_local(
    VECTOR_STORE_DIR, 
    embeddings, 
    allow_dangerous_deserialization=True
)
retriever = vectorstore.as_retriever(search_kwargs={"k": TOP_K})
print(f"✅ Loaded FAISS store ({vectorstore.index.ntotal} vectors)")

# ── Gemini LLM ────────────────────────────────────────────────────────────────
llm = ChatGoogleGenerativeAI(
    model=CHAT_MODEL,
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
)

# ── RAG Chain Setup ───────────────────────────────────────────────────────────

# 1. Contextualize Question Prompt
context_q_system_prompt = (
    "Given a chat history and the latest user question "
    "which might reference context in the chat history, "
    "formulate a standalone question. Do NOT answer it, just reformulate."
)
context_q_prompt = ChatPromptTemplate.from_messages([
    ("system", context_q_system_prompt),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])
history_aware_retriever = create_history_aware_retriever(llm, retriever, context_q_prompt)

# 2. Answer Question Prompt
system_prompt = (
    "You are a helpful assistant. Use the following context to answer.\n\n"
    "{context}"
)
qa_prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])
question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)

# 3. Final Chain
rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

# ── Session Memory ────────────────────────────────────────────────────────────
_chat_histories = {} 

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=".")
CORS(app)

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    query = (data.get("message") or "").strip()
    session_id = data.get("session_id", "default")

    if not query:
        return jsonify({"error": "Empty message"}), 400

    if session_id not in _chat_histories:
        _chat_histories[session_id] = []

    try:
        result = rag_chain.invoke({
            "input": query, 
            "chat_history": _chat_histories[session_id]
        })

        answer = result["answer"]
        
        # Update History
        _chat_histories[session_id].extend([
            HumanMessage(content=query),
            AIMessage(content=answer),
        ])
        _chat_histories[session_id] = _chat_histories[session_id][-10:]

        sources = list({
            os.path.basename(doc.metadata.get("source", "unknown"))
            for doc in result.get("context", [])
        })

        return jsonify({"answer": answer, "sources": sources})

    except Exception as exc:
        print(f"❌ Error: {exc}")
        return jsonify({"error": "Service busy. Check API quota."}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)

