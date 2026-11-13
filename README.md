# Insurance Assistant

An English-language question-answering application for exploring insurance documents. It searches local text files for relevant passages and uses an OpenRouter language model to generate answers grounded in those passages.

The included documents describe insurance legislation in Azerbaijan and are intended for testing. **This project is not a source of legal advice.** Check answers against authoritative, up-to-date sources.

## Features

- Browser interface and FastAPI endpoints.
- Hybrid document retrieval using sentence embeddings and BM25 keyword search.
- English answers with retrieved document names, without invented page numbers.
- Docker Compose setup with a health check.

The `sources` field lists retrieved documents; it does not guarantee that each document supports the answer. The current application reads `.txt` files, not PDFs.

## Requirements

- Docker and Docker Compose.
- An OpenRouter API key and a model available to your OpenRouter account.
- Internet access to build the image and to generate answers through OpenRouter.

## Getting Started

1. Create `App/.env` and add your own API key. Replace the placeholder; do not include quotes or commit the real key.

   ```dotenv
   OPENROUTER_API_KEY=your_openrouter_api_key
   LLM_MODEL=liquid/lfm-3-1.7b:free
   EMBED_MODEL=intfloat/multilingual-e5-base
   ```

   `LLM_MODEL` and `EMBED_MODEL` are optional; the values above are the application defaults. You can choose a different OpenRouter model if it is available to your account.

2. From the project root, build and start the application:

   ```sh
   docker compose --env-file App/.env up -d --build
   ```

   The first build downloads Python dependencies and the embedding model. Startup loads the model and indexes the text documents in memory, so it may take a little time.

3. Open `http://localhost:8000/` for the interface, `http://localhost:8000/docs` for interactive API documentation, or `http://localhost:8000/health` to check readiness and the number of indexed chunks.

## Using the API

Send a question of 3-500 characters to `POST /ask`:

```json
{
  "question": "Which law sets the general framework for insurance contracts?"
}
```

The response contains an `answer` string and a `sources` list of document names:

```json
{
  "answer": "Example answer based on the retrieved documents.",
  "sources": [{"doc": "02_civil_code.txt"}]
}
```

If no sufficiently relevant information is found, the application returns a not-found answer and an empty sources list. An unavailable answer-generation service returns HTTP 503.

## Documents and Configuration

Place UTF-8 `.txt` documents in `data/index/`. The application splits them into chunks and builds an in-memory search index on startup. Rebuild and recreate the container after adding or changing documents:

```sh
docker compose --env-file App/.env up -d --build
```

`EMBED_MODEL` selects the local sentence-transformer model used for retrieval; it is not the model that writes answers. Its default supports multiple languages, while the answer prompt requests English. Because the model is downloaded during the Docker build, rebuild the image after changing `EMBED_MODEL`.

After changing other environment settings, recreate the container to load them:

```sh
docker compose --env-file App/.env up -d --force-recreate
```

To inspect logs or stop the application:

```sh
docker compose --env-file App/.env logs -f api
docker compose --env-file App/.env down
```

## Tests

In a Python environment with the application's dependencies and PyTorch installed, run:

```sh
python -m unittest discover -s tests
```

## Security and Privacy

- Keep `App/.env` and API keys private. The repository's `.gitignore` excludes environment files, but ignored files already tracked by Git remain tracked; check before pushing.
- Questions and retrieved document excerpts are sent to OpenRouter for answer generation. Do not use sensitive documents unless that data sharing is appropriate.
- The example texts are test material. Review both the documents and generated answers before relying on them.

## Project Structure

```text
App/                 API, retrieval, model configuration, and web interface
data/index/          Text documents used for retrieval
tests/               Application tests
Dockerfile           Application image definition
docker-compose.yml   Local container configuration
```
