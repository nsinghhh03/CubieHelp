from __future__ import annotations

"""Utility functions exposed to the LLM for analytics queries.

This module keeps the database-execution logic in one place so that
main.py can import and register the functions when operating in
"analytics" mode.
"""

import re
from typing import Any, List, Dict
import logging

from uuid import uuid4
import os, io, base64
import plotly.express as px

# basic logging config (only once)
logging.basicConfig(level=logging.INFO, format="[analytics_tools] %(levelname)s: %(message)s")

import pandas as pd

from database import run_query

# --- simple safety checker -------------------------------------------------
_READ_ONLY_PATTERN = re.compile(r"^\s*select\b", re.IGNORECASE)
_DISALLOWED_PATTERN = re.compile(r"\b(drop|delete|update|insert|alter|truncate)\b", re.IGNORECASE)


def _validate_sql(sql: str) -> None:
    """Raise ValueError if *sql* is not a safe, read-only SELECT statement."""
    if not _READ_ONLY_PATTERN.match(sql):
        raise ValueError("Only SELECT statements are permitted.")
    if _DISALLOWED_PATTERN.search(sql):
        raise ValueError("Dangerous keyword detected; query rejected.")


# --- tools -----------------------------------------------------------------

_MACROS: Dict[str, str] = {
    "{{CURRENT_YEAR}}": "YEAR(GETDATE())",
    "{{CURRENT_MONTH}}": "MONTH(GETDATE())",
}


def _expand_macros(sql: str) -> str:
    """Replace known macro tokens in the SQL with their T-SQL equivalent."""
    for token, replacement in _MACROS.items():
        sql = sql.replace(token, replacement)
    return sql


def _run_and_serialize(query: str) -> str:
    """Internal helper: run query and return JSON string."""
    logging.info("SQL run: %s", query)
    df = run_query(query)
    if df.empty:
        return '[{"notice":"no_rows"}]'
    return df.to_json(orient="records")  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Chart generation (Plotly)
# ---------------------------------------------------------------------------

def chart_tool(sql: str, chart_type: str, x: str, y: str, title: str | None = None, z: str | None = None) -> str:
    """Execute SQL, render a Plotly chart, save to PNG, return static URL.

    Parameters
    ----------
    sql: read-only SELECT statement.
    chart_type: "line" | "bar" | "stacked_bar".
    x, y: column names in result set to map to axes.
    title: optional chart title.
    """
    _validate_sql(sql)
    sql = _expand_macros(sql)

    df = run_query(sql)
    if df.empty:
        return '[{"notice":"no_rows"}]'

    if chart_type == "line":
        fig = px.line(df, x=x, y=y, title=title)
    elif chart_type == "bar":
        fig = px.bar(df, x=x, y=y, title=title)
    elif chart_type == "stacked_bar":
        # Expect y to be a list of numeric columns for stacking
        y_cols = [col.strip() for col in y.split(',')]
        fig = px.bar(df, x=x, y=y_cols, title=title)
    elif chart_type == "heatmap":
        # If a z-column is provided use it, else count occurrences
        if z:
            fig = px.density_heatmap(df, x=x, y=y, z=z, color_continuous_scale="Blues")
        else:
            fig = px.density_heatmap(df, x=x, y=y, color_continuous_scale="Blues")
    else:
        raise ValueError("Unsupported chart_type")

    fig.update_layout(
        template="plotly_white",
        width=600,
        height=350,
        legend_title="",
        font=dict(family="Montserrat, sans-serif")
    )

    # Ensure output directory exists
    out_dir = "public/demo"
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{uuid4().hex}.png"
    path = os.path.join(out_dir, fname)
    fig.write_image(path, format="png", engine="kaleido")

    # Return HTML anchor wrapping the image so clicking downloads the PNG.
    # The download attribute triggers browser save dialog.
    return (
        f'<a href="/static/demo/{fname}" download="chart.png" class="chart-dl">'
        f'<img src="/static/demo/{fname}" alt="Chart" /></a>'
    )


def sql_tool(sql: str) -> str:
    """Execute a single validated SELECT query and return JSON rows."""
    _validate_sql(sql)
    sql = _expand_macros(sql)
    return _run_and_serialize(sql)


def multi_sql_tool(queries: List[str]) -> List[str]:
    """Run multiple read-only queries and return list of JSON result strings."""
    results: List[str] = []
    for q in queries:
        _validate_sql(q)
        q = _expand_macros(q)
        results.append(_run_and_serialize(q))
    return results


def percentage_tool(numerator_sql: str, denominator_sql: str) -> str:
    """Compute percentage = SUM(numerator_result) / SUM(denominator_result) * 100.

    Each SQL should return a single row with a single numeric column.
    Returns a JSON string with keys numerator, denominator, percent.
    """
    import json

    # Run both queries
    num_json = sql_tool(numerator_sql)
    den_json = sql_tool(denominator_sql)

    num_val = float(pd.read_json(num_json).iloc[0, 0]) if num_json != "[]" else 0.0
    den_val = float(pd.read_json(den_json).iloc[0, 0]) if den_json != "[]" else 0.0
    percent = (num_val / den_val * 100.0) if den_val else None

    return json.dumps({
        "numerator": num_val,
        "denominator": den_val,
        "percent": percent,
    })

# ---------------------------------------------------------------------------
# Dispute management mutation + email helper
# ---------------------------------------------------------------------------
import smtplib, ssl, mimetypes, json
from email.message import EmailMessage
import pymssql
from database import DB_SERVER, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_ADDR = os.getenv("FROM_ADDR", SMTP_USER)


def _execute_non_query(sql: str) -> None:
    """Execute an INSERT/UPDATE/DELETE statement."""
    conn = pymssql.connect(
        server=DB_SERVER,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
    )
    cursor = conn.cursor()
    cursor.execute(sql)
    conn.commit()
    conn.close()


def update_dispute_status(dispute_id: int, new_status: str | None, changed_by: str) -> str:
    """Set DisputeStatus to 'Open' or 'Closed'. If *new_status* is None, toggle it."""

    if not new_status:
        # fetch current status
        df = run_query(f"SELECT DisputeStatus FROM DisputeManagement WHERE DisputeID={int(dispute_id)}")
        if df.empty:
            raise ValueError("DisputeID not found")
        curr = str(df.iloc[0, 0]).strip().capitalize()
        status_norm = "Closed" if curr == "Open" else "Open"
    else:
        status_norm = new_status.strip().capitalize()

    if status_norm not in {"Open", "Closed"}:
        raise ValueError("new_status must be 'Open' or 'Closed'")

    safe_user = changed_by.replace("'", "''")
    query = (
        f"UPDATE DisputeManagement SET DisputeStatus='{status_norm}', "
        f"ChangedOn=GETDATE(), ChangedBy='{safe_user}' "
        f"WHERE DisputeID={int(dispute_id)};"
    )
    _execute_non_query(query)
    return status_norm.lower()


def add_audit_comment(dispute_id: int, comments: str, processor: str | None = None, assigned_to: str | None = None) -> str:
    """Insert a comment row into AuditTrail."""
    proc_val = (processor or "Cubie").replace("'", "''")
    comm_val = comments.replace("'", "''")
    assign_val = (assigned_to or "").replace("'", "''")
    query = (
        f"INSERT INTO AuditTrail (DisputeID, CreationDate, Processor, Comments, AssignedTo) "
        f"VALUES ({int(dispute_id)}, GETDATE(), '{proc_val}', '{comm_val}', '{assign_val}');"
    )
    _execute_non_query(query)
    return "inserted"


def _emails_for_usernames(usernames: list[str]) -> list[str]:
    """Resolve usernames *or* raw email addresses to email addresses."""
    if not usernames:
        return []

    direct_emails = [u for u in usernames if "@" in u]
    lookup_users  = [u for u in usernames if "@" not in u]

    results: list[str] = direct_emails.copy()

    if lookup_users:
        quoted = ",".join(f"'{u.lower()}'" for u in lookup_users)
        sql = (
            "SELECT EmailId FROM UserProfile "
            f"WHERE LOWER(UserName) IN ({quoted})"
        )
        df = run_query(sql)
        if not df.empty:
            results.extend(df["EmailId"].dropna().tolist())

    # de-dup and return
    return list({e.lower(): e for e in results}.values())


def clean_email_content(content: str) -> str:
    """Clean up email content by removing markdown formatting and unnecessary characters."""
    import re
    
    # Remove markdown bold formatting (**text** -> text)
    content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)
    
    # Remove markdown italic formatting (*text* -> text)
    content = re.sub(r'\*(.*?)\*', r'\1', content)
    
    # Remove markdown headers (# Header -> Header)
    content = re.sub(r'^#+\s*', '', content, flags=re.MULTILINE)
    
    # Remove markdown list formatting (- item -> item)
    content = re.sub(r'^-\s*', '', content, flags=re.MULTILINE)
    
    # Remove markdown code blocks (```code``` -> code)
    content = re.sub(r'```.*?\n(.*?)\n```', r'\1', content, flags=re.DOTALL)
    
    # Remove markdown inline code (`code` -> code)
    content = re.sub(r'`(.*?)`', r'\1', content)
    
    # Clean up extra whitespace
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    content = content.strip()
    
    return content


def draft_email_tool(to_usernames: list[str], subject: str, body_markdown: str, attachments: list[str] | None = None) -> str:
    """Create an email draft for approval before sending."""
    recipients = _emails_for_usernames(to_usernames)
    if not recipients:
        return "no_recipients"

    # Clean up the email content
    clean_body = clean_email_content(body_markdown)
    
    # Add Cubie signature if not present
    if not clean_body.rstrip().endswith("Cubie"):
        clean_body += "\n\n— Cubie"
    
    # Create draft info
    draft_info = {
        "recipients": recipients,
        "subject": subject,
        "body": clean_body,
        "attachments": attachments or [],
        "status": "draft",
    }
    
    # Store draft globally (in a real app, you'd use a database)
    global EMAIL_DRAFT
    EMAIL_DRAFT = draft_info
    print(f"DEBUG: Stored EMAIL_DRAFT: {EMAIL_DRAFT}")
    
    # Return formatted draft for display
    return f"DRAFT_EMAIL:{json.dumps(draft_info)}"


def mail_tool(to_usernames: list[str], subject: str, body_markdown: str, attachments: list[str] | None = None) -> str:
    """Send an email via SMTP to given usernames (resolved to EmailId)."""
    recipients = _emails_for_usernames(to_usernames)
    if not recipients:
        return "no_recipients"

    print(f"DEBUG: mail_tool called with recipients: {recipients}")
    print(f"DEBUG: SMTP_HOST: {SMTP_HOST}, SMTP_USER: {SMTP_USER}")
    
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR or SMTP_USER
    msg["To"] = ", ".join(recipients)
    
    # Clean up the email content before sending
    clean_body = clean_email_content(body_markdown)
    if not clean_body.rstrip().endswith("Cubie"):
        clean_body += "\n\n— Cubie"
    
    msg.set_content(clean_body)

    # Infer attachment paths from body_markdown if none supplied
    if (not attachments or len(attachments) == 0) and "/static/demo/" in body_markdown:
        import re
        paths = re.findall(r"/static/demo/\S+?\.png", body_markdown)
        attachments = list(set(paths))

    for path in attachments or []:
        # Map /static/xyz to filesystem path public/xyz for reading
        fs_path = path
        if path.startswith("/static/"):
            fs_path = os.path.join("public", path[len("/static/"):])
        mime, _ = mimetypes.guess_type(fs_path)
        maintype, subtype = (mime or "application/octet-stream").split("/")
        try:
            with open(fs_path, "rb") as fp:
                msg.add_attachment(fp.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(path))
        except FileNotFoundError:
            continue

    context = ssl.create_default_context()
    try:
        print(f"DEBUG: Attempting to connect to SMTP server {SMTP_HOST}:{SMTP_PORT}")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            print(f"DEBUG: Connected to SMTP server")
            server.starttls(context=context)
            print(f"DEBUG: Started TLS")
            server.login(SMTP_USER, SMTP_PASS)
            print(f"DEBUG: Logged in successfully")
            server.send_message(msg)
            print(f"DEBUG: Email sent successfully")
    except Exception as exc:
        print(f"DEBUG: SMTP error: {exc}")
        return f"error: {exc}"
    return "sent"


def approve_email_tool() -> str:
    """Send the approved email draft."""
    global EMAIL_DRAFT
    print(f"DEBUG: approve_email_tool called, EMAIL_DRAFT: {EMAIL_DRAFT}")
    if not EMAIL_DRAFT:
        print("DEBUG: No EMAIL_DRAFT found")
        return "no_draft"
    
    print(f"DEBUG: Sending email with draft: {EMAIL_DRAFT}")
    # Send the email using the draft
    result = mail_tool(
        EMAIL_DRAFT["recipients"],
        EMAIL_DRAFT["subject"], 
        EMAIL_DRAFT["body"],
        EMAIL_DRAFT["attachments"]
    )
    
    # Clear the draft
    EMAIL_DRAFT = None
    print(f"DEBUG: Email sent, result: {result}")
    
    return result


# Global variable to store email draft
EMAIL_DRAFT = None