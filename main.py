import os
import json
import numpy as np
import openai
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from numpy.linalg import norm
from typing import cast, List, Dict
from openai.types.chat import ChatCompletionMessageParam
from uuid import uuid4

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
    # First pass: filter out 'under construction' docs
    for doc, emb in zip(documents, embeddings):
        section = doc.get('section_title', '').lower()
        content = doc.get('content', '').lower()
        if "under construction" in section or "under construction" in content:
            continue
        sim = cosine_similarity(query_embedding, emb)
        boosted = boost_score(sim, doc, query)
        scored_docs.append((boosted, doc))
    # If nothing left after filtering, fall back to all docs
    if not scored_docs:
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

# Mount static files
app.mount("/static", StaticFiles(directory="public"), name="static")

@app.get("/", response_class=HTMLResponse)
def root():
    with open("public/index.html", "r") as f:
        return HTMLResponse(content=f.read())

# === In-memory conversation context (single user, for dev/testing) ===
conversation_history = [
    {"role": "system", "content": (
        "You are Cubie, a helpful and upbeat customer service assistant for Tcube.\n"
        "Your goal is to provide clear, concise, and friendly answers grounded in the help documentation.\n\n"
        "Instructions:\n"
        "- Always use a polite, friendly, and conversational tone.\n"
        "- If the user asks for humor (e.g., jokes), respond playfully.\n"
        "- When giving instructions, always use bullet points (-) or numbered lists (1., 2., ...) with spacing.\n"
        "- When referencing links:\n"
        "   • Use [descriptive link text](URL) instead of raw URLs.\n"
        "- Do not repeat greetings in each response.\n"
        "- If you don't know the answer, say so politely.\n"
        "- Responses must always be formatted using valid Markdown syntax.\n\n"
        "Help Context:"
    )}
]

@app.post("/api/query")
async def handle_query(request: Request):
    try:
        body = await request.json()
        query = body.get("question")
        prefs = body.get("prefs", {})
        if not query:
            return JSONResponse(status_code=400, content={"error": "Missing 'question' in request."})

        # --- Greeting shortcut ---
        greeting_keywords = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
        if query.strip().lower() in greeting_keywords:
            reply = "Hello! I'm Cubie, your personal supply chain assistant. How can I assist you today?"
            conversation_history.append({"role": "assistant", "content": reply})
            return JSONResponse({"reply": reply})
        # --- End greeting shortcut ---

        # Build help context for this turn
        top_docs = search_documents(query)
        context = build_context([doc for _, doc in top_docs])

        # --- Build dynamic system prompt with user preferences ---
        system_prompt = (
            "You are Cubie, a helpful and upbeat customer service assistant for Tcube.\n"
            "Your goal is to provide clear, concise, and friendly answers grounded in the help documentation.\n\n"
            "Instructions:\n"
            "- Always use a polite, friendly, and conversational tone.\n"
            "- If the user asks for humor (e.g., jokes), respond playfully.\n"
            "- When giving instructions, always use bullet points (-) or numbered lists (1., 2., ...) with spacing.\n"
            "- When referencing links:\n"
            "   • Use [descriptive link text](URL) instead of raw URLs.\n"
            "- Do not repeat greetings in each response.\n"
            "- If you don't know the answer, say so politely.\n"
            "- Responses must always be formatted using valid Markdown syntax.\n\n"
            "Help Context:"
        )
        # Add user preferences to the system prompt
        if prefs.get("name"):
            system_prompt += f"\n\nThe user's preferred name is: {prefs['name']}. Greet them by this name in your first message only."
        if prefs.get("length"):
            system_prompt += f"\n\nRespond with {prefs['length']} length answers."
        if prefs.get("traits"):
            traits = prefs['traits']
            if 'cheerful' in traits:
                system_prompt += "\n\nBe cheerful, use exclamation points, and maintain an optimistic tone."
            if 'playful' in traits:
                system_prompt += "\n\nBe playful: use emojis and add a joke or light humor when appropriate."
            if 'neutral' in traits:
                system_prompt += "\n\nMaintain a neutral, balanced tone."
            if 'professional' in traits:
                system_prompt += "\n\nBe professional and businesslike."

        # Use a fresh conversation history for each request to ensure system prompt is updated
        conversation = [
            {"role": "system", "content": system_prompt}
        ]
        # Add previous conversation if needed (or just current user message)
        user_message = f"{query}\n\nHelp Context:\n{context}"
        conversation.append({"role": "user", "content": user_message})

        # Cast conversation to the correct type for OpenAI
        messages = cast(list[ChatCompletionMessageParam], conversation)

        # Call OpenAI API with the full conversation history
        completion = openai.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.5
        )

        reply = completion.choices[0].message.content
        if reply is None:
            reply = "I apologize, but I couldn't generate a response. Please try again."
        else:
            reply = reply.strip()

        # Optionally, add assistant reply to conversation history if you want to keep context
        # conversation_history.append({"role": "assistant", "content": reply})

        return JSONResponse({"reply": reply})

    except Exception as e:
        import traceback
        print("Error during /api/query request:")
        traceback.print_exc()  # This prints the full error in your terminal
        return JSONResponse(status_code=500, content={"error": str(e)})

