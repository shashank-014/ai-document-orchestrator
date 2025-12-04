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

    IMPORTANT:
    - We force the model to always return the SAME keys.
    - We also strip ```json ... ``` fences here so n8n receives clean JSON.
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
   - "invoice_date": string or null           # issue date on the invoice
   - "vendor_name": string or null            # supplier / company name
   - "total_amount": string or null           # full amount including currency (e.g. "$93.50")
   - "due_date": string or null               # payment due date
   - "risk_level": "High" | "Medium" | "Low"  # subjective risk based on content

3. Return ONLY valid JSON. 
   - Do NOT wrap it in markdown.
   - NO ```json fences.
   - NO extra comments or text.

Example of the EXACT format to return:

{{
  "invoice_number": "INV-123",
  "invoice_date": "2024-01-31",
  "vendor_name": "ACME Corp",
  "total_amount": "$123.45",
  "due_date": "2024-02-15",
  "risk_level": "Low"
}}
"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )

    raw = (response.text or "").strip()

    # Strip common markdown fences, just in case
    cleaned = (
        raw.replace("```json", "")
           .replace("```JSON", "")
           .replace("```", "")
           .strip()
    )

    # We **return a JSON string**, because n8n expects "structured_data" as string
    return cleaned


def send_to_n8n(context: dict):
    """POST full context to n8n webhook."""
    try:
        resp = requests.post(
            N8N_WEBHOOK_URL,
            json=context,
            timeout=90,
        )

        if resp.status_code == 200:
            st.success("✅ Sent to n8n successfully.")
            # Try to show JSON if possible
            try:
                st.subheader("Response from n8n (test)")
                st.json(resp.json())
            except json.JSONDecodeError:
                st.write(resp.text)
        else:
            st.error(f"❌ n8n returned status {resp.status_code}: {resp.text}")

    except Exception as e:
        st.error(f"❌ Error sending to n8n: {e}")


# --------------------------
# STREAMLIT APP
# --------------------------

def main():
    st.set_page_config(page_title="AI Document Orchestrator", layout="centered")

    st.title("AI-Powered Document Orchestrator")
    st.caption("Upload any invoice in pdf format")

    # --- Keep data across clicks ---
    if "raw_text" not in st.session_state:
        st.session_state.raw_text = None
    if "structured_data" not in st.session_state:
        st.session_state.structured_data = None
    if "question" not in st.session_state:
        st.session_state.question = ""

    # ---------- STEP 1 & 2: Upload + Gemini ----------
    uploaded_file = st.file_uploader("Upload PDF/TXT", type=["pdf", "txt"])
    question = st.text_input(
        "Enter your analytical question about this document",
        value=st.session_state.question,
        key="question_input",
    )

    if st.button("Run Gemini Extraction", key="extract_btn"):
        if not uploaded_file:
            st.error("Please upload a document first.")
            return
        if not question.strip():
            st.error("Please enter a question.")
            return

        with st.spinner("Extracting raw text..."):
            raw_text = extract_text_from_file(uploaded_file)

        if not raw_text.strip():
            st.error("Could not extract any text from this document.")
            return

        with st.spinner("Calling Gemini for structured extraction..."):
            structured = extract_structured_data(raw_text, question)

        st.session_state.raw_text = raw_text
        st.session_state.structured_data = structured
        st.session_state.question = question

        st.success("Extraction complete ✅")

    # ---------- SHOW RESULTS IF AVAILABLE ----------
    if st.session_state.structured_data:
        st.subheader("Structured Data (from Gemini)")

        # Try to pretty-print as JSON for readability
        structured = st.session_state.structured_data
        try:
            parsed_obj = json.loads(structured)
            st.code(json.dumps(parsed_obj, indent=2), language="json")
        except Exception:
            # If parsing fails, just show raw text
            st.code(structured, language="json")

        st.subheader("Raw Extracted Text (Preview)")
        st.text_area(
            "Document Text",
            st.session_state.raw_text[:4000] if st.session_state.raw_text else "",
            height=250,
        )

        # ---------- STEP 3 (TEST): Send to n8n ----------
        st.markdown("---")
        st.subheader("Step 3 (Test): Send alert context to n8n")

        recipient_email = st.text_input(
            "Recipient Email ID (for later Gmail step)",
            key="recipient_email",
            placeholder="someone@example.com",
        )

        if st.button("Send Alert Mail (to n8n webhook)", key="send_n8n_btn"):
            if not recipient_email.strip():
                st.error("Please enter a recipient email.")
            else:
                context = {
                    "question": st.session_state.question,
                    # still send as STRING (n8n Parse JSON node will handle it)
                    "structured_data": st.session_state.structured_data,
                    "raw_text": st.session_state.raw_text,
                    "recipient_email": recipient_email,
                }
                with st.spinner("Sending context to n8n webhook..."):
                    send_to_n8n(context)


if __name__ == "__main__":
    main()
