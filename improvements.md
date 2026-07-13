# ChatBot Project — Code Review & Implementation Recommendations

Repo reviewed: `Shreyans3700/ChatBot`
Stack: FastAPI + LangChain + Groq + PostgreSQL (asyncpg)

---

## TL;DR

This is a solid **stateful conversational LLM service** (prompt-chain + persisted chat history), not a RAG pipeline. It's well-structured for a learning project — clean separation of concerns, parameterized SQL, proper async lifecycle management, and a real SSE streaming implementation. Below are bugs to fix, design gaps to shore up, and a path to turn it into an actual RAG project worth putting on a resume.

---

## 1. Bugs to Fix

### 1.1 `/getSessionHistory` probably doesn't work as documented

**File:** `app.py`

```python
@app.get("/getSessionHistory")
async def get_session_history(request: SessionHistoryRequest) -> SessionHistoryResponse:
```

FastAPI treats a bare Pydantic model parameter as a **request body**, regardless of HTTP verb. Your README documents calling this with a query string:

```
curl "http://localhost:8000/getSessionHistory?session_id=demo-session"
```

That query param will not populate `request.session_id`. This will likely 422.

**Fix:**

```python
from fastapi import Query

@app.get("/getSessionHistory", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str = Query(..., min_length=1, max_length=128)) -> SessionHistoryResponse:
    history = await get_session_history_from_db(session_id=session_id, db=app.state.db)
    return SessionHistoryResponse(session_id=session_id, history=history)
```

You can now drop `SessionHistoryRequest` entirely, or keep it only if you still want a shared schema elsewhere.

**Action items:**
- [ ] Update the endpoint signature to use `Query(...)`
- [ ] Test with the exact curl command from the README
- [ ] Update `SessionHistoryRequest` usage/remove if unused elsewhere

---

### 1.2 "Token trimming" is actually message-count trimming

**File:** `src/db.py`

```python
return trim_messages(
    history,
    max_tokens=MAX_CHAT_HISTORY_MESSAGES,
    token_counter=lambda messages: len(messages),
    strategy="last",
    allow_partial=True,
)
```

`trim_messages` is designed for token-aware trimming, but the `token_counter` here just counts messages. Functionally fine (and your env var is honestly named `MAX_CHAT_HISTORY_MESSAGES`), but it's not doing what the API name implies — worth fixing for correctness and because "token-aware context management" is a much stronger resume bullet than "keep last N messages."

**Fix (real token counting):**

```python
import tiktoken

# pick an encoding close to your model family; cl100k_base is a reasonable default
_encoding = tiktoken.get_encoding("cl100k_base")

def _count_tokens(messages) -> int:
    return sum(len(_encoding.encode(str(m.content))) for m in messages)

history = trim_messages(
    history,
    max_tokens=MAX_CHAT_HISTORY_TOKENS,   # rename the env var to reflect reality
    token_counter=_count_tokens,
    strategy="last",
    allow_partial=True,
)
```

**Action items:**
- [ ] Add `tiktoken` to `requirements.txt`
- [ ] Replace the message-count lambda with a real token counter
- [ ] Rename `MAX_CHAT_HISTORY_MESSAGES` → `MAX_CHAT_HISTORY_TOKENS` (env var + `.env` + README)

---

### 1.3 Streaming event matching is fragile

**File:** `src/llm.py`, inside `stream_answer`

```python
elif event_type in {"on_chat_model_end", "on_llm_end", "on_chain_end"}:
```

`ChatPromptTemplate` is also a runnable in your chain (`qa_prompt | llm`), so its `on_chain_end` fires too — with a `ChatPromptValue`, not an `AIMessage`. Your code currently works only because event ordering happens to put the outer chain's `on_chain_end` (with real metadata) last, so it overwrites the earlier no-op values. That's correct by accident, not by design — it'll silently break if you restructure the chain (e.g., add a retriever step, add output parsing, add a second LLM call).

**Fix — filter by run name instead of just event type:**

```python
elif event_type in {"on_chat_model_end", "on_llm_end"}:
    # only fires for the actual LLM step, immune to chain restructuring
    ...
```

Drop `on_chain_end` from the set entirely and rely only on the LLM-specific events, which always carry proper `AIMessage`/`response_metadata`.

**Action items:**
- [ ] Remove `on_chain_end` from the matched event types
- [ ] Re-test streaming to confirm metadata still populates correctly

---

## 2. Design Gaps (not bugs, but worth addressing)

### 2.1 No authentication or rate limiting

Every endpoint is open. Fine for a portfolio project, but flag it explicitly rather than let it look like an oversight.

**Minimal fix — API key header:**

```python
from fastapi import Header, HTTPException

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != required_setting("API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")

# then per-route:
@app.post("/chat", response_model=ResponseModel, dependencies=[Depends(verify_api_key)])
```

**Action items:**
- [ ] Add `API_KEY` to `.env`
- [ ] Add the dependency to `/chat` and `/chat/stream`
- [ ] Add a rate limiter (e.g. `slowapi`) if this will ever be public-facing
- [ ] Document the auth model in the README even if you don't implement it yet

### 2.2 Dead dependency

`requirements.txt` includes `streamlit` with no Streamlit code in the repo.

**Action items:**
- [ ] Remove `streamlit` from `requirements.txt`, or add a minimal Streamlit front-end if you actually want one (would also be a nice resume-visual for demos)

### 2.3 Hardcoded DB port

**File:** `src/config.py`

```python
port=int("5432"),
```

Should read from env for flexibility (e.g. Docker port remapping, managed Postgres on a non-default port).

**Fix:**
```python
port=int(os.getenv("DB_PORT", "5432")),
```

**Action items:**
- [ ] Read `DB_PORT` from env with a `5432` default
- [ ] Add `DB_PORT` to `.env` example in README

### 2.4 No tests

Even a couple of `httpx.AsyncClient` tests against `/chat` with a mocked LLM would meaningfully strengthen this repo for interview purposes — testing discipline stands out especially for a data engineering role.

**Action items:**
- [ ] Add `pytest` + `pytest-asyncio` + `httpx`
- [ ] Mock `app.state.chain` and `app.state.db` in a fixture
- [ ] Cover: happy path `/chat`, DB failure → 502, session history retrieval

---

## 3. The Big One: Turn This Into an Actual RAG Project

Right now there's no retriever, no vector store, no document ingestion — it's prompt-chaining with persisted memory, not RAG. If you want to legitimately list "RAG" and "Vector Databases" on your resume against this project, add real retrieval. Since you're already on Postgres, **pgvector** is the path of least new infrastructure.

### Plan

1. **Add pgvector extension** to your existing Postgres instance:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

2. **Ingestion pipeline** (new module, e.g. `src/ingest.py`):
   - Load documents (start simple: PDFs or markdown files)
   - Chunk with `RecursiveCharacterTextSplitter`
   - Embed with a Groq-compatible or separate embedding model (Groq doesn't serve embeddings — use `HuggingFaceEmbeddings` locally, or OpenAI/Cohere embeddings if you want hosted)
   - Store in a `langchain_postgres.PGVector` collection

3. **Retrieval chain** (update `src/config.py` / `src/llm.py`):
   ```python
   from langchain.chains import create_history_aware_retriever, create_retrieval_chain
   from langchain.chains.combine_documents import create_stuff_documents_chain

   history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_prompt)
   qa_chain = create_stuff_documents_chain(llm, qa_prompt)
   rag_chain = create_retrieval_chain(history_aware_retriever, qa_chain)
   ```
   This is exactly the pattern you've been studying — `create_history_aware_retriever` handles turning follow-up questions ("what about the second one?") into standalone queries using chat history before hitting the retriever.

4. **Wire into existing endpoints** — `/chat` and `/chat/stream` stay largely the same shape, just swap `chain.ainvoke(...)` for the new `rag_chain.ainvoke(...)` with a `context` key added to the prompt.

5. **New endpoint** for ingestion/upload if you want it to be a full demo:
   ```
   POST /documents  →  accepts a file, chunks + embeds + stores it
   ```

### Resulting resume bullet (once implemented)

> Built an end-to-end conversational RAG service (FastAPI, LangChain, PostgreSQL/pgvector) with history-aware retrieval, persistent multi-turn memory, and SSE token streaming — deployed via Docker.

That's interview-defensible because every clause maps to code you can point to and explain line-by-line.

---

## Priority Order

If you want to tackle this incrementally:

1. Fix `/getSessionHistory` (quick, real bug)
2. Fix streaming event filtering (quick, real bug)
3. Remove dead `streamlit` dependency (trivial)
4. Add real token-based trimming (moderate, resume-relevant)
5. Add basic API key auth (moderate)
6. Add pgvector + retrieval chain (larger, but this is the one that changes what you can honestly claim on your resume)
7. Add tests (ongoing, do alongside the above)