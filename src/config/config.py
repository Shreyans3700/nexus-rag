import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from pymilvus import DataType, Function, FunctionType, MilvusClient

from src.config.prompts import system_prompt, title_prompt
from src.logger import get_logger

MAX_CHAT_TOKENS = int(os.getenv("MAX_CHAT_TOKENS", "2500"))
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)
PASSWORD_HASH_ITERATIONS = int(os.getenv("PASSWORD_HASH_ITERATIONS", "210000"))

chat_model = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Milvus settings
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "doc_chunks")
MILVUS_TOP_K = int(os.getenv("MILVUS_TOP_K", "5"))
MILVUS_HYBRID_CANDIDATE_K = int(os.getenv("MILVUS_HYBRID_CANDIDATE_K", "20"))
MILVUS_RRF_K = int(os.getenv("MILVUS_RRF_K", "60"))
# token format: "username:password" — default Milvus root credentials are root:Milvus
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "root:Milvus")

# Cross-encoder reranking settings. The model is loaded lazily on the first
# retrieval so application startup remains fast.
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2"
)
RERANKER_CANDIDATE_K = int(os.getenv("RERANKER_CANDIDATE_K", "30"))
RERANKER_TOP_K = int(os.getenv("RERANKER_TOP_K", str(MILVUS_TOP_K)))
RERANKER_MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "512"))

# Embedding vector dimension for text-embedding-3-small
EMBEDDING_DIM = 1536


def required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


logger = get_logger(__name__)

llm = ChatOpenAI(
    model=chat_model,
    api_key=required_setting("OPENAI_API_KEY"),
    temperature=0.6,
    max_retries=3,
    max_tokens=6000,
)


def _bootstrap_milvus_collection(client: MilvusClient, collection_name: str) -> None:
    """Create the doc_chunks collection with all required fields if it does not exist."""
    if client.has_collection(collection_name):
        description = client.describe_collection(collection_name)
        field_names = {
            field.get("name") or field.get("field_name")
            for field in description.get("fields", [])
        }
        if "page" not in field_names:
            raise RuntimeError(
                f"Milvus collection '{collection_name}' uses the pre-citation schema. "
                "Milvus 2.5 does not support adding fields to an existing collection. "
                "Drop and recreate the collection, clear existing document records, "
                "then re-upload documents so page metadata can be indexed."
            )
        logger.info("Milvus collection already exists: %s", collection_name)
        return

    logger.info("Creating Milvus collection: %s", collection_name)
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("document_id", DataType.VARCHAR, max_length=64)
    schema.add_field("user_id", DataType.VARCHAR, max_length=128)
    schema.add_field("session_id", DataType.VARCHAR, max_length=128)
    schema.add_field("chunk_index", DataType.INT32)
    schema.add_field("page", DataType.INT32, nullable=True)
    schema.add_field("filename", DataType.VARCHAR, max_length=512)
    schema.add_field("text", DataType.VARCHAR, max_length=4096, enable_analyzer=True)
    schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
    schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(
        Function(
            name="text_bm25",
            function_type=FunctionType.BM25,
            input_field_names=["text"],
            output_field_names=["sparse_vector"],
        )
    )

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="dense_vector",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        params={"nlist": 128},
    )
    index_params.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
    )

    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )
    logger.info("Milvus collection created: %s", collection_name)


@asynccontextmanager
async def set_environment(app: FastAPI):
    logger.info("Initializing application environment")

    # ------------------------------------------------------------------ #
    # LangChain prompt + chain                                            #
    # {context} is populated by the retriever before each chain call.    #
    # When no documents exist for the session, context="" and the        #
    # prompt renders cleanly with just the existing chat history.        #
    # ------------------------------------------------------------------ #
    app.state.qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),   # system_prompt contains {context}
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{query}"),
        ]
    )
    app.state.title_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", title_prompt),
            ("human", "{query}"),
        ]
    )
    app.state.chain = app.state.qa_prompt | llm
    app.state.title_chain = app.state.title_prompt | llm

    # ------------------------------------------------------------------ #
    # PostgreSQL pool + schema                                            #
    # ------------------------------------------------------------------ #
    logger.debug("Creating database pool")
    app.state.db = await asyncpg.create_pool(
        host=required_setting("PG_HOST"),
        port=int(required_setting("PG_PORT")),
        database=required_setting("PG_DATABASE"),
        user=required_setting("PG_USER"),
        password=required_setting("PG_PASSWORD"),
        min_size=1,
        max_size=int(os.getenv("DB_POOL_SIZE", "10")),
    )

    try:
        async with app.state.db.acquire() as connection:
            logger.debug("Ensuring database schema and indexes")
            # --- existing tables ---
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    title TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('Human', 'AI')),
                    content TEXT NOT NULL,
                    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS messages_session_id_id_idx
                    ON messages (session_id, id);
                CREATE INDEX IF NOT EXISTS sessions_user_id_idx
                    ON sessions (user_id);
                """
            )
            await connection.execute(
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT"
            )
            await connection.execute(
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'::jsonb"
            )

            # --- RAG: document metadata table ---
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    chunk_count INT NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'processing'
                );
                CREATE INDEX IF NOT EXISTS documents_user_session_idx
                    ON documents (user_id, session_id);
                """
            )

            # --- RAG: chunk persistence table (Milvus fallback) ---
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chunk_index INT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    page INT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS document_chunks_session_id_idx
                    ON document_chunks (session_id);
                CREATE INDEX IF NOT EXISTS document_chunks_document_id_idx
                    ON document_chunks (document_id);
                """
            )
            await connection.execute(
                "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page INT"
            )

        logger.info("PostgreSQL schema ready")

        # ------------------------------------------------------------------ #
        # Milvus connection + collection bootstrap                           #
        # ------------------------------------------------------------------ #
        logger.debug(
            "Connecting to Milvus: host=%s port=%s", MILVUS_HOST, MILVUS_PORT
        )
        milvus_client = MilvusClient(
            uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}",
            token=MILVUS_TOKEN,
        )
        _bootstrap_milvus_collection(milvus_client, MILVUS_COLLECTION_NAME)
        app.state.milvus = milvus_client
        logger.info("Milvus ready: collection=%s", MILVUS_COLLECTION_NAME)

        logger.info("Application environment initialized")
        yield

    finally:
        logger.info("Closing database pool")
        await app.state.db.close()
        logger.info("Application shutdown complete")
