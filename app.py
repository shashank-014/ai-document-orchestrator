import streamlit as st
import pdfplumber
import requests
import json
from google import genai

# --------------------------
# CONFIG
# --------------------------

# Gemini client (key from Streamlit secrets)
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# n8n webhook URL (from secrets)
N8N_WEBHOOK_URL = st.secrets["N8N_WEBHOOK_URL"]

# --------------------------
# HELPERS
# --------------------------

def extract_text_from_file(uploaded_file):
    """Extract raw text from PDF or TXT."""
    if uploaded_file.name.endswith(".txt"):
        return uploaded_file.read().decode("utf-8")

    if uploaded_file.name.endswith(".pdf"):
        with pdfplumber.open(uploaded_file) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
        return full_text

    return ""


def extract_structured_data(text, question):
    """
    Call Gemini to get structured JSON.
    Always returns RAW JSON STRING (no markdown).
    """

    prompt = f"""
You are an AI that extracts invoice metadata.

Document Text:
{text}

User Question:
{question}

Your task:
1. Read the document and answer the question.
2. Extract the following fields from the document (if present):

   - "invoice_number": string or null
   - "invoice_date": string or null
   - "vendor_name": string or null
   - "total_amount": string or null
   - "due_date": string or null
   - "risk_level": "High" | "Medium" | "Low"

3. Return ONLY valid JSON.
   - NO markdown
   - NO ```json fences
   - NO commentary text

Exact format:

{{
  "invoice_number": "INV-123",
  "invoice_date": "2024-01-31",
  "vendor_name": "ACME Corp",
  "total_amount": "$123.45",
  "due_date": "2024-02-15",
  "risk_level": "Low"
}}
"""

    try:
        response = client.models.generate_content(
            model="models/gemini-1.5-flash-001",
            contents=prompt,
        )
    except Exception as e:
        import traceback
        st.error("🔥 GEMINI ERROR: " + str(e))
        st.code(traceback.format_exc())
        return json.dumps({"error": str(e)})

    raw = (response.text or "").strip()

    # Strip markdown fences JUST IN CASE
    cleaned = (
        raw.replace("```json", "")
           .replace("```JSON", "")
           .replace("```", "")
           .strip()
    )

    return cleaned


def send_to_n8n(context: dict):
    """POST full context to n8n webhook."""
    try:
        resp = requests.post(
