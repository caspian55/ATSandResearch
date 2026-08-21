import streamlit as st
from research_graph import research_app
from ats_analyzer import analyze_resume
from utils import extract_resume_text, create_ats_docx
import os

st.set_page_config(page_title="Improved Multi-Source Research + ATS", layout="wide")
st.title("🔬 Multi-Source Research Assistant + 📄 ATS Resume Tool (Ollama Mistral)")

# Session memory
if "research_history" not in st.session_state:
    st.session_state.research_history = []

tab1, tab2 = st.tabs(["Research Assistant", "ATS Resume Analyzer"])

with tab1:
    st.subheader("Multi-Agent Multi-Source Research")
    query = st.text_area("Research question", height=100)
    
    col1, col2 = st.columns([1, 3])
    with col1:
        run = st.button("Start Deep Research", type="primary")
    
    if run and query.strip():
        with st.status("Running research pipeline...", expanded=True) as status:
            st.write("Planning sub-questions...")
            result = research_app.invoke({
                "query": query,
                "sub_questions": [],
                "sources": [],
                "findings": "",
                "verification_notes": "",
                "final_report": "",
                "review_count": 0,
                "messages": []
            })
            status.update(label="Research complete!", state="complete")
        
        st.markdown("### Final Report")
        st.markdown(result["final_report"])
        
        with st.expander("Verification Notes"):
            st.write(result.get("verification_notes", ""))
        
        with st.expander("Sub-questions & Raw Findings"):
            st.write(result["sub_questions"])
            st.text(result["findings"][:5000])
        
        st.session_state.research_history.append({
            "query": query,
            "report": result["final_report"]
        })
    
    if st.session_state.research_history:
        st.markdown("---")
        st.subheader("Previous Research")
        for i, item in enumerate(reversed(st.session_state.research_history[-5:])):
            with st.expander(f"{item['query'][:60]}..."):
                st.markdown(item["report"])

with tab2:
    st.subheader("Hybrid ATS Analyzer + Full Resume Tailoring")
    
    resume_file = st.file_uploader("Upload Resume (PDF / DOCX)", type=["pdf", "docx"])
    jd_text = st.text_area("Paste Job Description", height=220)
    
    if st.button("Analyze & Generate Tailored Resume", type="primary"):
        if not resume_file or not jd_text.strip():
            st.warning("Please upload resume and paste JD.")
        else:
            with st.spinner("Running deterministic + LLM analysis..."):
                resume_text = extract_resume_text(resume_file)
                result = analyze_resume(resume_text, jd_text)
            
            st.metric("Overall ATS Score", f"{result['overall_score']}/100")
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Keyword Match", f"{result['keyword_score']}/100")
            c2.metric("Format Score", f"{result['format_score']}/100")
            c3.metric("Content Score", f"{result['content_score']}/100")
            
            if result["structure_issues"]:
                st.warning("Structure issues detected:")
                for issue in result["structure_issues"]:
                    st.write(f"- {issue}")
            
            st.markdown("### Matched Keywords")
            st.write(", ".join(result["matched_keywords"][:15]) or "None")
            
            st.markdown("### Missing Important Keywords")
            st.write(", ".join(result["missing_keywords"]) or "None")
            
            st.markdown("### Strengths")
            for s in result["strengths"]:
                st.success(s)
            
            st.markdown("### Gaps & Suggestions")
            for g in result["gaps"]:
                st.warning(g)
            for sug in result["suggestions"]:
                st.info(sug)
            
            st.markdown("### Tailored Professional Summary")
            st.write(result["tailored_summary"])
            
            st.markdown("### Recommended Skills")
            st.write(", ".join(result["tailored_skills"]))
            
            st.markdown("### Tailored Experience Bullets")
            for b in result["tailored_experience"]:
                st.write(f"• {b}")
            
            # Export
            docx_bytes = create_ats_docx(
                name="Your Name",
                summary=result["tailored_summary"],
                skills=result["tailored_skills"],
                experience="\n".join(f"• {b}" for b in result["tailored_experience"]),
                education=result["education"]
            )
            st.download_button(
                "Download ATS-Friendly DOCX",
                data=docx_bytes,
                file_name="tailored_resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

st.sidebar.markdown("""
### Setup (Ollama)
1. Install Ollama → https://ollama.com
2. `ollama pull mistral`
3. `pip install -r requirements.txt`
4. `streamlit run app.py`

Everything runs locally. No API keys needed.
""")