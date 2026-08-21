from typing import TypedDict, List, Annotated, Literal
from langgraph.graph import StateGraph, START, END
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from ddgs import DDGS
import arxiv
import wikipedia
from pydantic import BaseModel, Field
import operator

# ---------- LLM (Ollama Mistral) ----------
llm = ChatOllama(
    model="mistral",          # or "mistral:latest" / "mistral-nemo"
    temperature=0.2,
    num_ctx=8192
)

# ---------- Tools (Multi-source) ----------
@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the general web using DuckDuckGo."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        formatted = []
        for r in results:
            formatted.append(f"Title: {r.get('title')}\nURL: {r.get('href')}\nSnippet: {r.get('body')}")
        return "\n\n---\n\n".join(formatted) if formatted else "No web results found."
    except Exception as e:
        return f"Web search error: {str(e)}"

@tool
def arxiv_search(query: str, max_results: int = 4) -> str:
    """Search academic papers on arXiv."""
    try:
        search = arxiv.Search(query=query, max_results=max_results, sort_by=arxiv.SortCriterion.Relevance)
        papers = []
        for result in search.results():
            papers.append(
                f"Title: {result.title}\nAuthors: {', '.join(a.name for a in result.authors[:3])}\n"
                f"Published: {result.published.date()}\nURL: {result.entry_id}\nAbstract: {result.summary[:600]}..."
            )
        return "\n\n---\n\n".join(papers) if papers else "No arXiv papers found."
    except Exception as e:
        return f"arXiv error: {str(e)}"

@tool
def wikipedia_search(query: str) -> str:
    """Get a Wikipedia summary for background knowledge."""
    try:
        page = wikipedia.page(query, auto_suggest=True)
        return f"Title: {page.title}\nURL: {page.url}\nSummary: {page.summary[:1200]}"
    except Exception as e:
        return f"Wikipedia error: {str(e)}"

tools = [web_search, arxiv_search, wikipedia_search]
tools_by_name = {t.name: t for t in tools}

# ---------- State ----------
class Source(TypedDict):
    title: str
    url: str
    content: str
    source_type: str

class ResearchState(TypedDict):
    query: str
    sub_questions: List[str]
    sources: Annotated[List[Source], operator.add]
    findings: str
    verification_notes: str
    final_report: str
    review_count: int
    messages: Annotated[list, operator.add]

# ---------- Structured Planner ----------
class SubQuestions(BaseModel):
    questions: List[str] = Field(description="3 to 5 focused research sub-questions")

def planner(state: ResearchState):
    prompt = f"""You are an expert research planner.
Break the following query into 3-5 clear, non-overlapping sub-questions that together fully cover the topic.
Return only the list of questions.

Query: {state['query']}"""
    
    structured_llm = llm.with_structured_output(SubQuestions)
    try:
        result = structured_llm.invoke(prompt)
        questions = result.questions[:5]
    except Exception:
        # Fallback
        response = llm.invoke(prompt)
        questions = [q.strip("- ").strip() for q in response.content.split("\n") if q.strip()][:5]
    
    return {"sub_questions": questions, "review_count": 0}

def researcher(state: ResearchState):
    """Search all sources for every sub-question and collect structured sources."""
    all_sources = []
    findings_parts = []
    
    for q in state["sub_questions"]:
        findings_parts.append(f"### Sub-question: {q}\n")
        
        # Web
        web_res = web_search.invoke({"query": q, "max_results": 4})
        findings_parts.append(f"**Web:**\n{web_res}\n")
        
        # arXiv
        arxiv_res = arxiv_search.invoke({"query": q, "max_results": 3})
        findings_parts.append(f"**arXiv:**\n{arxiv_res}\n")
        
        # Wikipedia (only once per run is enough, but we keep it simple)
        if len(all_sources) < 3:  # limit Wikipedia calls
            wiki_res = wikipedia_search.invoke({"query": q})
            findings_parts.append(f"**Wikipedia:**\n{wiki_res}\n")
        
        # Very simple source extraction (for tracking)
        all_sources.append({
            "title": f"Research for: {q}",
            "url": "multi-source",
            "content": web_res[:800] + "\n" + arxiv_res[:800],
            "source_type": "mixed"
        })
    
    return {
        "findings": "\n".join(findings_parts),
        "sources": all_sources
    }

def verifier(state: ResearchState):
    """Simple verification / hallucination check."""
    prompt = f"""You are a critical fact-checker.
Review the research findings below against the original query.
Point out any claims that seem weakly supported, contradictory, or potentially hallucinated.
Suggest what is solid and what needs more evidence.
Be concise.

Original Query: {state['query']}

Findings:
{state['findings'][:6000]}
"""
    response = llm.invoke(prompt)
    return {"verification_notes": response.content}

def synthesizer(state: ResearchState):
    prompt = f"""You are a professional research writer.
Write a clear, well-structured Markdown research report.

Requirements:
- Start with an Executive Summary
- Use the findings and verification notes
- Include inline citations like [Web], [arXiv], [Wikipedia] where appropriate
- End with a short Conclusion and list of key sources
- Be factual. Do not invent information.

Original Query: {state['query']}

Verification Notes:
{state.get('verification_notes', '')}

Findings:
{state['findings'][:7000]}
"""
    response = llm.invoke(prompt)
    return {"final_report": response.content}

def should_continue(state: ResearchState) -> Literal["researcher", "synthesizer"]:
    """Simple self-correction: if verification is very negative and we haven't retried, go back."""
    notes = state.get("verification_notes", "").lower()
    if state["review_count"] < 1 and ("weak" in notes or "contradict" in notes or "insufficient" in notes):
        return "researcher"
    return "synthesizer"

def increment_review(state: ResearchState):
    return {"review_count": state.get("review_count", 0) + 1}

# ---------- Build Graph ----------
def build_research_graph():
    graph = StateGraph(ResearchState)
    
    graph.add_node("planner", planner)
    graph.add_node("researcher", researcher)
    graph.add_node("verifier", verifier)
    graph.add_node("increment", increment_review)
    graph.add_node("synthesizer", synthesizer)
    
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "verifier")
    graph.add_conditional_edges("verifier", should_continue, {
        "researcher": "increment",
        "synthesizer": "synthesizer"
    })
    graph.add_edge("increment", "researcher")
    graph.add_edge("synthesizer", END)
    
    return graph.compile()

research_app = build_research_graph()