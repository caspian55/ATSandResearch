from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import List, Dict
import re
from utils import simple_keyword_extract

llm = ChatOllama(model="mistral", temperature=0.1, num_ctx=8192)

# ---------- Deterministic parts ----------
STANDARD_HEADINGS = [
    "summary", "professional summary", "objective", "experience", "work experience",
    "education", "skills", "technical skills", "projects", "certifications", "publications"
]

def deterministic_keyword_score(resume: str, jd: str) -> Dict:
    resume_kw = set(simple_keyword_extract(resume, 50))
    jd_kw = set(simple_keyword_extract(jd, 40))
    
    if not jd_kw:
        return {"score": 0, "matched": [], "missing": []}
    
    matched = resume_kw.intersection(jd_kw)
    missing = list(jd_kw - resume_kw)[:15]
    
    score = int(len(matched) / len(jd_kw) * 100)
    return {
        "score": min(score, 100),
        "matched": list(matched)[:20],
        "missing": missing
    }

def structure_check(resume: str) -> Dict:
    text_lower = resume.lower()
    found_headings = [h for h in STANDARD_HEADINGS if h in text_lower]
    
    issues = []
    if len(found_headings) < 3:
        issues.append("Few standard section headings detected (Experience, Education, Skills recommended)")
    if "\t" in resume or resume.count("|") > 5:
        issues.append("Possible table or multi-column layout detected (bad for many ATS)")
    if len(resume) < 300:
        issues.append("Resume seems too short")
    
    # Very rough format score
    format_score = 70 + len(found_headings) * 5
    format_score = max(30, min(95, format_score - len(issues) * 15))
    
    return {
        "format_score": format_score,
        "found_headings": found_headings,
        "issues": issues
    }

# ---------- LLM qualitative + rewrite ----------
class ATSAnalysis(BaseModel):
    content_score: int = Field(description="Content quality & impact score 0-100")
    strengths: List[str]
    gaps: List[str]
    suggestions: List[str]
    tailored_summary: str
    tailored_skills: List[str]
    tailored_experience_bullets: List[str]
    education_section: str

def analyze_resume(resume_text: str, jd_text: str) -> Dict:
    # 1. Deterministic scores
    kw = deterministic_keyword_score(resume_text, jd_text)
    structure = structure_check(resume_text)
    
    # 2. LLM part (with retry)
    prompt = ChatPromptTemplate.from_template("""
You are an expert ATS resume coach and career writer.

Job Description:
{jd}

Candidate Resume:
{resume}

Tasks:
1. Give a content_score (0-100) based on quantified impact, relevance, and clarity.
2. List 3-5 strengths.
3. List 3-5 gaps.
4. Give concrete suggestions.
5. Write a strong tailored Professional Summary (3-4 lines).
6. Suggest 8-12 skills that should appear (prioritize JD keywords the candidate actually has).
7. Rewrite 4-6 strong experience bullets tailored to the JD (keep them truthful).
8. Write a clean Education section.

Return valid JSON matching the schema.
""")
    
    structured_llm = llm.with_structured_output(ATSAnalysis)
    
    for attempt in range(3):
        try:
            result = structured_llm.invoke(prompt.format(
                jd=jd_text[:4000],
                resume=resume_text[:10000]
            ))
            break
        except Exception as e:
            if attempt == 2:
                # Final fallback
                result = ATSAnalysis(
                    content_score=60,
                    strengths=["Could not fully analyze"],
                    gaps=["LLM parsing failed"],
                    suggestions=["Try again or shorten resume"],
                    tailored_summary="Experienced professional seeking new opportunities.",
                    tailored_skills=kw["matched"][:8],
                    tailored_experience_bullets=["See original resume"],
                    education_section="See original resume"
                )
    
    # Combine scores
    overall = int(
        kw["score"] * 0.40 +
        structure["format_score"] * 0.25 +
        result.content_score * 0.35
    )
    
    return {
        "overall_score": overall,
        "keyword_score": kw["score"],
        "format_score": structure["format_score"],
        "content_score": result.content_score,
        "matched_keywords": kw["matched"],
        "missing_keywords": kw["missing"],
        "structure_issues": structure["issues"],
        "strengths": result.strengths,
        "gaps": result.gaps,
        "suggestions": result.suggestions,
        "tailored_summary": result.tailored_summary,
        "tailored_skills": result.tailored_skills,
        "tailored_experience": result.tailored_experience_bullets,
        "education": result.education_section
    }