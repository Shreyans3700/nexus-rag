# nexus-rag

EndToEndChatBot is a FastAPI-based chatbot application that uses LangChain and OpenAI to generate responses while keeping chat history in PostgreSQL for each authenticated user. It includes a full **RAG (Retrieval-Augmented Generation) pipeline** — upload documents to a session, and the chatbot will ground its answers using the most relevant chunks from those documents.

## Features

- FastAPI backend with chat and streaming endpoints
- JWT-based signup and login
- Persistent user, session, and message history in PostgreSQL
- LangChain prompt chaining with an OpenAI chat model
- Configurable recent-message context window via environment variable
- **RAG pipeline**: upload PDF, DOCX, TXT, MD, or CSV files per session
- **Milvus hybrid search**: semantic vectors + BM25 keyword ranking fused with RRF
- **User-aware retrieval**: searches the current session first, then the user's other sessions when the current session has no documents
- Background document ingestion (upload returns instantly, embedding happens async)
- Docker support for containerized deployment

## Tech Stack

- Python 3.11
- FastAPI
- LangChain
- LangChain OpenAI
- asyncpg
- PostgreSQL
- Milvus (vector store)
- Streamlit
- Docker

## Prerequisites

Before running the project, make sure you have:

- Python 3.11+
- PostgreSQL running and reachable
- **Milvus Standalone** running (see Docker Compose section below)
- An OpenAI API key for the backend model
- A strong JWT secret for signing user tokens

## Environment Variables

Create a `.env` file in the project root with the following variables:

```env
OPENAI_API_KEY=your_openai_api_key
JWT_SECRET=your_long_random_jwt_secret
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
PASSWORD_HASH_ITERATIONS=210000
LLM_MODEL=gpt-4o-mini
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=LangchainDB
PG_USER=postgres
PG_PASSWORD=postgres
DB_POOL_SIZE=10
MAX_CHAT_TOKENS=2500

# Milvus (RAG vector store)
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=doc_chunks
MILVUS_TOP_K=5
MILVUS_HYBRID_CANDIDATE_K=20
MILVUS_RRF_K=60
```

## Local Development

1. **Start Milvus** (requires Docker):

```bash
docker compose up -d
```

This starts etcd, MinIO, Milvus Standalone on port `19530`, and Attu at
`http://localhost:8001` for direct collection and chunk inspection. In Attu,
connect to `milvus:19530` with the configured Milvus credentials.

### Inspecting chunks with Attu

Attu is a local Milvus administration UI. It is independent of the FastAPI and
Streamlit applications, so chunk inspection does not expose an additional
chatbot API endpoint.

1. Start or update the service:

   ```bash
   docker compose up -d attu
   ```

2. Open [http://localhost:8001](http://localhost:8001).
3. Connect using the Docker-network address `milvus:19530` — do **not** use
   `localhost:19530`, which would refer to the Attu container itself.
4. Authenticate with the value configured in `MILVUS_TOKEN`. The development
   Compose configuration uses the standard `root` username and `Milvus`
   password unless you override it.
5. Open the `doc_chunks` collection (or the collection named by
   `MILVUS_COLLECTION_NAME`) and browse/query its entities. Each indexed chunk
   contains `text`, `filename`, `page`, `chunk_index`, `document_id`,
   `session_id`, and `user_id`, along with dense and sparse vectors.

Attu is intended for local development and administration. Do not expose port
`8001` publicly without putting it behind appropriate network access controls.

2. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate   # Linux/macOS
venv\Scripts\activate      # Windows
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Start the backend:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

5. Start the Streamlit frontend:

```bash
streamlit run frontend.py
```

The API will be available at `http://localhost:8000` and the frontend at `http://localhost:8501`.

## Authentication

- `POST /auth/signup` — creates a user and returns an access token.
- `POST /auth/login` — verifies credentials and returns an access token.
- Authenticated requests must include `Authorization: Bearer <token>`.

## RAG Usage

1. Log in from the sidebar.
2. In the chat input, attach one or more files (PDF, DOCX, TXT, MD, CSV).
3. The frontend shows per-file ingestion status (⏳ processing → ✅ ready).
4. Once ready, ask questions — answers will be grounded in your document content.
5. Documents in the current session are searched first. If it has no indexed documents, the search includes the user's documents from other sessions.

### Milvus migration

The hybrid schema is incompatible with the old dense-only collection. Before deploying this version, drop the existing `doc_chunks` collection in Milvus, restart the API, and upload documents again. If existing Postgres document rows are retained, clear them first as well so the UI does not show stale documents as ready. This version does not rebuild Milvus automatically.

The citation schema adds a nullable `page` field to both `document_chunks` and Milvus. Because the configured Milvus 2.5 server has an immutable collection schema, an existing `doc_chunks` collection must also be recreated and its documents re-uploaded. The API fails fast with a migration message instead of silently indexing uncitable PDF chunks.

## API Endpoints

### Auth

```bash
# Sign up
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "strong-password"}'

# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "strong-password"}'
```

### Chat

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"session_id": "demo-session", "user_query": "Hello!"}'

# Streaming
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"session_id": "demo-session", "user_query": "Tell me a short joke"}'
```

### Documents

```bash
# Upload files (session_id is a required form field)
curl -X POST http://localhost:8000/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "session_id=demo-session" \
  -F "files=@report.pdf" \
  -F "files=@notes.txt"

# List documents for a session
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/documents?session_id=demo-session"

# Delete a document
curl -X DELETE http://localhost:8000/documents/{document_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Session History

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/getSessionHistory?session_id=demo-session"
```

## Docker

Start the full stack (Milvus + etcd + MinIO) with:

```bash
docker compose up -d
```

To also containerize the FastAPI app, build and run:

```bash
docker build -t chatbot .
docker run --env-file .env -p 8000:8000 chatbot
```

## Notes

- The context sent to the model is trimmed to the most recent configured number of messages. Update `MAX_CHAT_HISTORY_MESSAGES` in `.env` to change the window.
- `MILVUS_TOP_K` controls how many document chunks are retrieved per query (default 5).
- The streaming endpoint falls back to the final end-of-stream answer when a model emits empty chunks.
- Document ingestion is asynchronous — the upload endpoint returns `202 Accepted` immediately. Poll `GET /documents?session_id=...` to watch status change from `processing` to `ready`.
