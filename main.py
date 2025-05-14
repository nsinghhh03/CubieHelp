import os
import json
import numpy as np
import openai
from dotenv import load_dotenv
from numpy.linalg import norm
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# === Load environment variables ===
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if api_key is None:
    raise ValueError("OPENAI_API_KEY not set in your .env file")
openai.api_key = api_key

# === Embedding and chat model ===
EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-3.5-turbo"

# === Load saved embeddings and documents ===
data = np.load("help_embeddings.npz", allow_pickle=True)
embeddings = data["embeddings"]
documents = data["documents"]

# === Embedding helper ===
def get_embedding(text, model=EMBED_MODEL):
    response = openai.embeddings.create(
        input=[text],
        model=model
    )
    return response.data[0].embedding

# === Cosine similarity ===
def cosine_similarity(a, b):
    return np.dot(a, b) / (norm(a) * norm(b))

# === Boosting logic (optional) ===
BOOST_TERMS = ['kpi', 'dashboard', 'visualization', 'metrics', 'summary', 'trend', 'table', 'shipment']
CUBE_TERMS = ['rate cube', 'audit cube', 'admin cube', 'track cube']

def boost_score(score, doc, query):
    content = (doc.get('section_title', '') + ' ' + doc.get('content', '')).lower()
    query = query.lower()
    keyword_boost = sum(1 for term in BOOST_TERMS if term in content and term in query) * 0.02
    cube_boost = 0.05 if any(cube in query and cube in (doc.get('cube') or '').lower() for cube in CUBE_TERMS) else 0
    return score + keyword_boost + cube_boost

# === Semantic search for top matching docs ===
def search_documents(query, top_k=3):
    query_embedding = get_embedding(query)
    scored_docs = []
    for doc, emb in zip(documents, embeddings):
        sim = cosine_similarity(query_embedding, emb)
        boosted = boost_score(sim, doc, query)
        scored_docs.append((boosted, doc))
    ranked = sorted(scored_docs, key=lambda x: x[0], reverse=True)
    return ranked[:top_k]

# === Format context for prompt ===
def build_context(docs):
    parts = []
    for doc in docs:
        section = doc["section_title"]
        content = doc.get("content", "")
        url = doc.get("source_url", "")
        parts.append(f"Section: {section}\nURL: {url}\nContent: {content}")
    return "\n\n".join(parts)

# === FastAPI Setup ===
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "FastAPI is running. Use POST /api/query to chat with Cubie."}

@app.post("/api/query")
async def handle_query(request: Request):
    try:
        body = await request.json()
        query = body.get("question")
        if not query:
            return JSONResponse(status_code=400, content={"error": "Missing 'question' in request."})

        top_docs = search_documents(query)
        context = build_context([doc for _, doc in top_docs])

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Cubie, a helpful and upbeat customer service assistant for Tcube.\n"
                    "Your goal is to provide clear, concise, and friendly answers grounded in the help documentation.\n\n"
                    "Instructions:\n"
                    "- Always use a polite, friendly, and conversational tone.\n"
                    "- If the user asks for humor (e.g., jokes), respond playfully.\n"
                    "- When giving instructions, always use bullet points (-) or numbered lists (1., 2., ...) with spacing.\n"
                    "- When referencing links:\n"
                    "   • Use [descriptive link text](URL) instead of raw URLs.\n"
                    "- Do not repeat greetings in each response.\n"
                    "- If you don’t know the answer, say so politely.\n"
                    "- Responses must always be formatted using valid Markdown syntax.\n\n"
                    f"Help Context:\n{context}"
                )
            },
            {
                "role": "user",
                "content": query
            }
        ]

        completion = openai.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.5
        )

        reply = completion.choices[0].message.content.strip()
        return JSONResponse({"reply": reply})

    except Exception as e:
        import traceback
        print("Error during /api/query request:")
        traceback.print_exc()  # This prints the full error in your terminal
        return JSONResponse(status_code=500, content={"error": str(e)})
