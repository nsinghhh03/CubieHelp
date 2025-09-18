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
from typing import cast, List, Dict, Any
from openai.types.chat import ChatCompletionMessageParam
from uuid import uuid4

import json as json_lib  # for parsing function arguments safely
from datetime import datetime

# noqa: F401 – explicit re-export (chart tools)
import analytics_tools as _at

from analytics_tools import sql_tool, multi_sql_tool, percentage_tool, chart_tool, update_dispute_status, add_audit_comment, mail_tool, draft_email_tool, approve_email_tool

# === Simple session storage for email drafts ===
# In a real app, you'd use Redis, database, or proper session management
EMAIL_DRAFTS: Dict[str, Dict[str, Any]] = {}

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

# === Load DB schema for analytics mode ===
try:
    with open("schema_prompt.txt", "r", encoding="utf-8") as _f:
        DB_SCHEMA = _f.read()
except FileNotFoundError:
    DB_SCHEMA = ""

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

# Globals to retain last assistant reply and chart paths
LAST_BODY: str = ""
LAST_CHARTS: list[str] = []

@app.post("/api/approve-email")
async def approve_email(request: Request):
    """Direct endpoint for approving email drafts without going through AI."""
    try:
        body = await request.json()
        session_id = body.get("session_id", "default")
        
        print(f"DEBUG: Direct approval request for session_id: {session_id}")
        print(f"DEBUG: EMAIL_DRAFTS keys: {list(EMAIL_DRAFTS.keys())}")
        
        if session_id in EMAIL_DRAFTS:
            draft_data = EMAIL_DRAFTS[session_id]
            print(f"DEBUG: Found draft in session storage: {draft_data}")
            
            # Send the email using the draft
            from analytics_tools import mail_tool
            result = mail_tool(
                draft_data["recipients"],
                draft_data["subject"], 
                draft_data["body"],
                draft_data["attachments"]
            )
            print(f"DEBUG: Email sent, result: {result}")
            
            # Clear the draft from session storage
            del EMAIL_DRAFTS[session_id]
            
            if result == "sent":
                reply = "✅ Email has been sent successfully!"
            else:
                reply = f"❌ Error sending email: {result}"
        else:
            print(f"DEBUG: No draft found in session storage")
            reply = "❌ No email draft found to approve."
        
        return JSONResponse({"reply": reply})
        
    except Exception as e:
        import traceback
        print("Error during /api/approve-email request:")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/query")
async def handle_query(request: Request):
    try:
        global LAST_BODY, LAST_CHARTS
        body = await request.json()
        query = body.get("question")
        mode = body.get("mode", "help")  # "help" or "analytics"
        prefs = body.get("prefs", {})
        conversation_history = body.get("history", [])  # Get conversation history from frontend
        if not query:
            return JSONResponse(status_code=400, content={"error": "Missing 'question' in request."})

        # --- placeholder for future prompt engineering / no hard-coded demos ---
        q_lower = query.lower()
        now = datetime.now()
        # (hard-coded demo removed)

        # --- Greeting shortcut ---
        greeting_keywords = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
        if query.strip().lower() in greeting_keywords:
            reply = "Hello! I'm Cubie, your personal supply chain assistant. How can I assist you today?"
            conversation_history.append({"role": "assistant", "content": reply})
            return JSONResponse({"reply": reply})
        # --- End greeting shortcut ---

        # Build help context only in help mode
        if mode == "help":
            top_docs = search_documents(query)
            context = build_context([doc for _, doc in top_docs])
        else:
            context = ""

        # --- Build dynamic system prompt based on mode ---
        if mode == "analytics":
            system_prompt = (
                "You are an analytics assistant for TCube.\n"
                "Use the database schema below to write read-only SQL queries.\n"
                "Never modify data. Always wrap SQL in a function call if needed.\n\n"
                f"{DB_SCHEMA}"
            )
            system_prompt += (
                "\n\nRules:\n"
                "• If the JSON you receive is [{\"notice\":\"no_rows\"}], reply: 'No data available for that query.'\n"
                "• Never display raw SQL in your answer.\n"
                "• Never respond with 'stay tuned' or similar filler; provide the numeric result directly.\n"
                "• Column naming reminders: use RecipientCountry/RecipientCity/RecipientState for destination fields,\n"
                "  use ShipperCountry/City/State for origin. Avoid non-existent columns like DestRegion.\n"
                "• In DisputeManagement the carrier column is CarrierCode (not TCCarrierCode).\n"
                "• When the user asks for 'top' items (carriers, disputes, etc.) default to TOP 3 unless they specify another number.\n"
                "• When the user inquires about a single Dispute ID, first retrieve its row from DisputeManagement, then all related AuditTrail comments, and also count total disputes for that CarrierCode to provide context. Summarize all three pieces of data.\n"
                "• Do NOT respond with a plan or outline. Always execute the required SQL queries via sql_tool (or other tools) first, then respond with the final ranked answer or summary.\n"
                "• If the user asks to email or send something, you MUST call draft_email_tool first to create a draft for approval. Use to_usernames for TCube usernames or direct email addresses (addresses contain '@'). Provide a clear subject and body.\n"
                "  After calling draft_email_tool, you MUST immediately show the email draft content in your response so the user can review it.\n"
                "  IMPORTANT: Always include the actual email content (recipients, subject, and body) in your response after calling draft_email_tool.\n"
                "  Example draft_email_tool call JSON (you must include to_usernames):\n"
                "    {\"to_usernames\":[\"VSINGH\"], \"subject\":\"Shipment KPI\", \"body_markdown\":\"Hi!\"}\n"
                "  If a chart PNG was generated in a previous step, include its /static/demo/filename.png in the attachments array so the user receives the image.\n"
                "  Do NOT send the email immediately - always show the draft first and wait for user approval.\n"
                "  If you do not include to_usernames the email will NOT be sent.\n"
                "• When chart_tool returns a URL, embed the image using Markdown like: ![Chart](URL).\n"
                "• You may chain multiple function calls until you have the final answer.\n"
            )
            functions_spec = [
                {
                    "name": "sql_tool",
                    "description": "Run a read-only SQL query and return JSON rows",
                    "parameters": {
                        "type": "object",
                        "properties": {"sql": {"type": "string"}},
                        "required": ["sql"]
                    },
                },
                {
                    "name": "multi_sql_tool",
                    "description": "Run multiple read-only SQL queries and return list of JSON result strings",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "queries": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["queries"]
                    },
                },
                {
                    "name": "percentage_tool",
                    "description": "Compute percentage using two SQL queries (numerator and denominator)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "numerator_sql": {"type": "string"},
                            "denominator_sql": {"type": "string"}
                        },
                        "required": ["numerator_sql", "denominator_sql"]
                    },
                },
                {
                    "name": "chart_tool",
                    "description": "Generate a Plotly chart for the given SQL result and return a static PNG URL",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string"},
                            "chart_type": {"type": "string"},
                            "x": {"type": "string"},
                            "y": {"type": "string"},
                            "title": {"type": "string"},
                            "z": {"type": "string"}
                        },
                        "required": ["sql", "chart_type", "x", "y"]
                    },
                },
                {
                    "name": "update_dispute_status",
                    "description": "Set a dispute's status to Open or Closed in DisputeManagement",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dispute_id": {"type": "integer"},
                            "new_status": {"type": "string"},
                            "changed_by": {"type": "string"}
                        },
                        "required": ["dispute_id", "changed_by"]
                    },
                },
                {
                    "name": "add_audit_comment",
                    "description": "Insert a comment row into AuditTrail for a dispute",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dispute_id": {"type": "integer"},
                            "comments": {"type": "string"},
                            "processor": {"type": "string"},
                            "assigned_to": {"type": "string"}
                        },
                        "required": ["dispute_id", "comments"]
                    },
                },
                {
                    "name": "draft_email_tool",
                    "description": "Create an email draft for approval before sending to TCube users",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to_usernames": {"type": "array", "items": {"type": "string"}},
                            "subject": {"type": "string"},
                            "body_markdown": {"type": "string"},
                            "attachments": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["to_usernames", "subject", "body_markdown"]
                    },
                },
                {
                    "name": "approve_email_tool",
                    "description": "Send the approved email draft",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    },
                },
            ]
        else:
            # default help-mode prompt (original)
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
            functions_spec = None

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

        # Use conversation history from frontend, but ensure system prompt is updated
        conversation = [
            {"role": "system", "content": system_prompt}
        ]
        # Add previous conversation history from frontend
        conversation.extend(conversation_history)
        # Add current user message
        user_message = f"{query}\n\nHelp Context:\n{context}"
        conversation.append({"role": "user", "content": user_message})

        # Cast conversation to the correct type for OpenAI
        messages = cast(list[ChatCompletionMessageParam], conversation)

        if mode == "analytics":
            # Check for email approval/rejection in analytics mode
            user_message_lower = user_message.lower().strip()
            if user_message_lower in ["approve", "approved", "yes", "send", "send it"]:
                # User approved the email draft
                print(f"DEBUG: User approved email in analytics mode, checking for draft...")
                session_id = "default"  # In a real app, you'd get this from the request
                print(f"DEBUG: Checking session storage for session_id: {session_id}")
                print(f"DEBUG: EMAIL_DRAFTS keys: {list(EMAIL_DRAFTS.keys())}")
                
                if session_id in EMAIL_DRAFTS:
                    draft_data = EMAIL_DRAFTS[session_id]
                    print(f"DEBUG: Found draft in session storage: {draft_data}")
                    
                    # Send the email using the draft
                    from analytics_tools import mail_tool
                    result = mail_tool(
                        draft_data["recipients"],
                        draft_data["subject"], 
                        draft_data["body"],
                        draft_data["attachments"]
                    )
                    print(f"DEBUG: Email sent, result: {result}")
                    
                    # Clear the draft from session storage
                    del EMAIL_DRAFTS[session_id]
                    
                    if result == "sent":
                        reply = "✅ Email has been sent successfully!"
                    else:
                        reply = f"❌ Error sending email: {result}"
                else:
                    print(f"DEBUG: No draft found in session storage")
                    reply = "❌ No email draft found to approve."
                return JSONResponse({"reply": reply})
            elif user_message_lower in ["reject", "rejected", "no", "cancel", "don't send"]:
                # User rejected the email draft
                session_id = "default"
                if session_id in EMAIL_DRAFTS:
                    del EMAIL_DRAFTS[session_id]
                    print(f"DEBUG: Cleared draft from session storage")
                reply = "❌ Email draft has been cancelled."
                return JSONResponse({"reply": reply})
            
            last_chart_snippet: str | None = None  # store latest chart HTML/Markdown from chart_tool
            # --- Multi-step agent loop ---
            while True:
                req_kwargs: dict[str, object] = {
                    "model": CHAT_MODEL,
                    "messages": messages,
                    "temperature": 0.3,
                }
                if functions_spec:
                    # OpenAI 1.x uses the "tools" param. The older "functions" param is now deprecated and
                    # cannot be sent alongside "tools". We therefore send only the "tools" list; the model
                    # will reply with the newer `tool_calls` format.
                    req_kwargs["tools"] = [{"type": "function", "function": spec} for spec in functions_spec]
                    req_kwargs["tool_choice"] = "auto"

                resp = openai.chat.completions.create(**req_kwargs)  # type: ignore[arg-type]
                msg_choice = resp.choices[0]

                # --------------------------------------------------------------
                # Handle both legacy (function_call) and new (tool_calls) formats
                # --------------------------------------------------------------
                fn_calls: list[dict] = []
                if msg_choice.finish_reason == "function_call" and msg_choice.message.function_call is not None:
                    # Old style – single function call
                    fn_calls.append({
                        "id": None,
                        "name": msg_choice.message.function_call.name,
                        "arguments": msg_choice.message.function_call.arguments or "{}",
                    })
                elif msg_choice.finish_reason == "tool_calls" and getattr(msg_choice.message, "tool_calls", None):
                    # New style – one or more tool calls
                    for tc in msg_choice.message.tool_calls:  # type: ignore[attr-defined]
                        fn_calls.append({
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        })

                if fn_calls:
                    print(f"DEBUG: Processing {len(fn_calls)} function calls")
                    # Ensure the original assistant tool_call message is added once
                    messages.append(msg_choice.message)

                    # Execute each function call sequentially (they are independent)
                    for call in fn_calls:
                        print(f"DEBUG: Processing function call: {call['name']}")
                        args = json_lib.loads(call["arguments"] or "{}")
                        if call["name"] == "sql_tool":
                            result = sql_tool(args.get("sql", ""))
                        elif call["name"] == "multi_sql_tool":
                            result = json_lib.dumps(multi_sql_tool(args.get("queries", [])))
                        elif call["name"] == "percentage_tool":
                            result = percentage_tool(args.get("numerator_sql", ""), args.get("denominator_sql", ""))
                        elif call["name"] == "chart_tool":
                            result = chart_tool(
                                args.get("sql", ""),
                                args.get("chart_type", "line"),
                                args.get("x", ""),
                                args.get("y", ""),
                                args.get("title", ""),
                                args.get("z", "")
                            )
                            if ("<img" in result) or ("![Chart" in result):
                                last_chart_snippet = result
                        elif call["name"] == "update_dispute_status":
                            result = update_dispute_status(
                                args.get("dispute_id"),
                                args.get("new_status"),
                                args.get("changed_by", "agent"),
                            )
                        elif call["name"] == "add_audit_comment":
                            result = add_audit_comment(
                                args.get("dispute_id"),
                                args.get("comments", ""),
                                args.get("processor", "agent"),
                                args.get("assigned_to", ""),
                            )
                        elif call["name"] == "draft_email_tool":
                            # Fill missing fields with last response context
                            to_users = args.get("to_usernames", [])
                            subject  = args.get("subject", "Assistance Summary")
                            body_md  = args.get("body_markdown", "") or LAST_BODY
                            attach   = args.get("attachments") or LAST_CHARTS
                            print(f"DEBUG: Calling draft_email_tool with to_users={to_users}, subject={subject}")
                            result = draft_email_tool(to_users, subject, body_md, attach)
                            print(f"DEBUG: draft_email_tool result: {result[:100]}...")
                            
                            # If this is a draft email result, we need to handle it specially
                            if result.startswith("DRAFT_EMAIL:"):
                                import json
                                try:
                                    draft_json = result[len("DRAFT_EMAIL:"):].strip()
                                    draft_data = json.loads(draft_json)
                                    
                                    # Store the draft in session storage
                                    session_id = "default"  # In a real app, you'd get this from the request
                                    EMAIL_DRAFTS[session_id] = draft_data
                                    print(f"DEBUG: Stored draft in session storage: {EMAIL_DRAFTS[session_id]}")
                                    
                                    # Create a formatted email preview
                                    email_preview = f"""📧 **Email Draft Ready for Approval**

**To:** {', '.join(draft_data['recipients'])}
**Subject:** {draft_data['subject']}

**Message:**
{draft_data['body']}

---
*Please review the email above and click the Approve button below to send it.*"""
                                    
                                    # Override the result to show the formatted preview
                                    result = email_preview
                                    print(f"DEBUG: Formatted email preview: {result[:100]}...")
                                    
                                    # Add the formatted result to messages and return immediately
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": call["id"],
                                        "content": result,
                                    })
                                    return JSONResponse({"reply": result})
                                except (json.JSONDecodeError, KeyError) as e:
                                    print(f"DEBUG: Error parsing draft email: {e}")
                                    pass  # Keep original result if parsing fails
                        elif call["name"] == "approve_email_tool":
                            result = approve_email_tool()
                        elif call["name"] == "mail_tool":
                            # Keep original mail_tool for backward compatibility
                            to_users = args.get("to_usernames", [])
                            subject  = args.get("subject", "Assistance Summary")
                            body_md  = args.get("body_markdown", "") or LAST_BODY
                            attach   = args.get("attachments") or LAST_CHARTS
                            result = mail_tool(to_users, subject, body_md, attach)
                        else:
                            result = "Unsupported function"

                        # Append tool result in correct format
                        if msg_choice.finish_reason == "function_call":
                            messages.append({
                                "role": "function",
                                "name": call["name"],
                                "content": result,
                            })
                        else:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": result,
                            })
                    # Continue agent loop for additional calls or final answer
                    continue

                # Otherwise, we have the final answer
                final_reply = msg_choice.message.content or "I couldn't generate a response."
                
                # Update globals for future email requests
                LAST_BODY = final_reply.strip()
                if last_chart_snippet:
                    import re
                    LAST_CHARTS = re.findall(r"/static/demo/\S+?\.png", last_chart_snippet)
                else:
                    LAST_CHARTS = []
                # If model forgot to include the chart markdown, prepend it
                if last_chart_snippet and ("<img" not in final_reply and "![Chart" not in final_reply):
                    # Prepend the chart snippet so it appears before text
                    final_reply = f"{last_chart_snippet}\n\n{final_reply}"
                return JSONResponse({"reply": final_reply.strip()})

        # ---------------- help mode (single step) ------------------

        # Check for email approval/rejection in help mode
        user_message_lower = user_message.lower().strip()
        if user_message_lower in ["approve", "approved", "yes", "send", "send it"]:
            # User approved the email draft
            print(f"DEBUG: User approved email, checking for draft...")
            session_id = "default"  # In a real app, you'd get this from the request
            print(f"DEBUG: Checking session storage for session_id: {session_id}")
            print(f"DEBUG: EMAIL_DRAFTS keys: {list(EMAIL_DRAFTS.keys())}")
            
            if session_id in EMAIL_DRAFTS:
                draft_data = EMAIL_DRAFTS[session_id]
                print(f"DEBUG: Found draft in session storage: {draft_data}")
                
                # Send the email using the draft
                from analytics_tools import mail_tool
                result = mail_tool(
                    draft_data["recipients"],
                    draft_data["subject"], 
                    draft_data["body"],
                    draft_data["attachments"]
                )
                print(f"DEBUG: Email sent, result: {result}")
                
                # Clear the draft from session storage
                del EMAIL_DRAFTS[session_id]
                
                if result == "sent":
                    reply = "✅ Email has been sent successfully!"
                else:
                    reply = f"❌ Error sending email: {result}"
            else:
                print(f"DEBUG: No draft found in session storage")
                reply = "❌ No email draft found to approve."
            return JSONResponse({"reply": reply})
        elif user_message_lower in ["reject", "rejected", "no", "cancel", "don't send"]:
            # User rejected the email draft
            session_id = "default"
            if session_id in EMAIL_DRAFTS:
                del EMAIL_DRAFTS[session_id]
                print(f"DEBUG: Cleared draft from session storage")
            reply = "❌ Email draft has been cancelled."
            return JSONResponse({"reply": reply})

        single_resp = openai.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.5,
        )

        reply = (single_resp.choices[0].message.content or "I couldn't generate a response.").strip()
        return JSONResponse({"reply": reply})

    except Exception as e:
        import traceback
        print("Error during /api/query request:")
        traceback.print_exc()  # This prints the full error in your terminal
        return JSONResponse(status_code=500, content={"error": str(e)})