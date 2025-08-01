import os
import json
import numpy as np
import openai
from dotenv import load_dotenv
from numpy.linalg import norm
from typing import cast
from openai.types.chat import ChatCompletionMessageParam


# Load API key
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("Missing OPENAI_API_KEY in .env")
openai.api_key = api_key

# Load embeddings and metadata
data = np.load("help_embeddings.npz", allow_pickle=True)
embeddings = data["embeddings"]
documents = data["documents"]

EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4"  # or "gpt-3.5-turbo" if cheaper

# Embedding function
def get_embedding(text, model=EMBED_MODEL):
    response = openai.embeddings.create(input=[text], model=model)
    return response.data[0].embedding

# Cosine similarity
def cosine_similarity(a, b):
    return np.dot(a, b) / (norm(a) * norm(b))

# Search top-k relevant help docs
def search_help_docs(query_embedding, top_k=3):
    results = []
    for doc, emb in zip(documents, embeddings):
        sim = cosine_similarity(query_embedding, emb)
        results.append((sim, doc))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:top_k]

# Build prompt for chat
def build_chat_prompt(top_docs, user_query):
    help_context = "\n\n".join(
        f"Section: {doc['section_title']}\nURL: {doc['source_url']}\nContent: {doc['content']}"
        for _, doc in top_docs
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant answering questions using the TCube help documentation. Be concise, informative, and cite section titles and URLs when helpful."},
        {"role": "user", "content": f"Refer to the following help documentation:\n\n{help_context}"},
        {"role": "user", "content": f"Question: {user_query}"}
    ]
    return messages


# Main loop
while True:
    user_input = input("\nAsk a question (or type 'exit'): ").strip()
    if user_input.lower() == "exit":
        break

    query_embedding = get_embedding(user_input)
    top_docs = search_help_docs(query_embedding, top_k=3)

    messages = build_chat_prompt(top_docs, user_input)
    messages = cast(list[ChatCompletionMessageParam], messages)
    response = openai.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.2
    )

    print(response.choices[0].message.content)


data = np.load("help_embeddings.npz", allow_pickle=True)
documents = data["documents"]

# Print first document to inspect keys
print(documents[0])
