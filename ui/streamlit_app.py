"""
Run:  streamlit run ui/streamlit_app.py
"""
import os

import requests
import streamlit as st

API = os.getenv("SCHEMAMIND_API", "http://127.0.0.1:8000")

st.set_page_config(page_title="SchemaMind", layout="wide")
st.title("SchemaMind")
st.caption("Ask questions in plain English about the sample shop database. "
           "The SQL it ran is always shown — never trust an answer you can't see the query for.")

with st.sidebar:
    st.subheader("Settings")
    top_k = st.slider("Tables to retrieve", 1, 5, 3)
    use_full = st.checkbox("Use full schema instead of retrieval", value=False)
    mode = st.radio("Generation mode", ["template", "mistral"], index=0,
                     help="template needs no API key but only handles a few "
                          "known question shapes. mistral is real text-to-SQL.")
    st.divider()
    try:
        h = requests.get(f"{API}/health", timeout=5).json()
        st.success("API up")
        st.write("Tables:", ", ".join(h.get("tables", [])))
    except Exception:
        st.error("API unreachable. Start it with `uvicorn app.api:app`.")

st.info("Try: *how many orders*, *top 5 customers by spend*, "
        "*orders from Indore*, *revenue by category*, *cancelled orders*")

question = st.text_input("Question", placeholder="top 5 customers by spend")

if st.button("Ask", type="primary") and question:
    try:
        r = requests.post(
            f"{API}/ask",
            json={"question": question, "top_k_tables": top_k,
                  "use_full_schema": use_full, "mode": mode},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.error(f"Request failed: {e}")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("Attempts", data["attempts"])
    c2.metric("Tables used", len(data["tables_used"]))
    c3.metric("Latency", f"{data['latency_ms']:.0f} ms")

    if data["sql"]:
        st.code(data["sql"], language="sql")

    if not data["ok"]:
        st.error(data["error"])
    else:
        if data["rows"]:
            st.dataframe(
                {col: [row[i] for row in data["rows"]] for i, col in enumerate(data["columns"])}
            )
        else:
            st.write("Query ran successfully but returned no rows.")

    st.caption(f"Schema used: {', '.join(data['tables_used'])}"
               f"{' (full schema)' if data['used_full_schema'] else ' (retrieved)'}")
