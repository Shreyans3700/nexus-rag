# Corpus frontend

React (Vite + TypeScript + Tailwind) UI for the nexus-rag chatbot API. See the
root `README.md` for the full project setup — this covers just the frontend.

## Local development

```bash
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` and talks to the API at
`VITE_API_BASE_URL` (defaults to `http://localhost:8000`). Copy `.env.example`
to `.env.local` to override it. The backend must have `FRONTEND_ORIGIN` set to
this app's origin so its CORS middleware allows the browser requests.

## Build

```bash
npm run build
```

Type-checks and produces a static bundle in `dist/`.

## Docker

```bash
docker build -t corpus-frontend --build-arg VITE_API_BASE_URL=http://localhost:8000 .
docker run -p 5173:80 corpus-frontend
```

Or via the root `docker-compose.yaml`: `docker compose up -d --build frontend`.
