"""Read-only public arXiv metadata discovery; records sources for attribution."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests

folder = Path(__file__).resolve().parents[1] / "artifacts/experiments/roles_v1/literature"
folder.mkdir(parents=True, exist_ok=True)
query = ('ti:"Rethinking Graph Neural Networks for Anomaly Detection" OR '
         'ti:"Simplifying Graph Convolutional Networks" OR '
         'ti:"SIGN" OR ti:"Predict then Propagate" OR '
         'ti:"Camouflaged Fraudsters" OR ti:"Graph Neural Networks for Directed Graphs" OR '
         'ti:"Fraud Detection" AND cat:cs.LG')
response = requests.get("https://export.arxiv.org/api/query", params={"search_query": query, "max_results": 25,
                        "sortBy": "relevance"}, timeout=45)
response.raise_for_status()
(folder / "arxiv.xml").write_text(response.text, encoding="utf-8")
namespace = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
papers = []
for entry in ET.fromstring(response.text).findall("a:entry", namespace):
    def value(path):
        item = entry.find(path, namespace)
        return " ".join(item.text.split()) if item is not None and item.text else None
    arxiv_id = re.sub(r"v\d+$", "", value("a:id").split("/")[-1])
    abstract = value("a:summary")
    urls = re.findall(r"https://github.com/[^\s)]+", abstract or "")
    paper = {"title": value("a:title"), "authors": [a.find("a:name", namespace).text for a in entry.findall("a:author", namespace)],
             "year": int(value("a:published")[:4]), "publication_date": value("a:published")[:10],
             "publication_type": "preprint", "venue": value("x:journal_ref"), "doi": value("x:doi"),
             "arxiv_id": arxiv_id, "abstract": abstract, "comment": value("x:comment"),
             "citation_count": None, "open_access_status": "green", "full_text_status": "open_pdf",
             "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}", "download_status": "not_requested",
             "code_url": urls[0].rstrip(".") if urls else None, "source_platforms": ["arxiv"],
             "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    papers.append(paper)
(folder / "papers.json").write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps([{k: paper[k] for k in ("title", "year", "venue", "arxiv_id", "comment")} for paper in papers], ensure_ascii=False, indent=2))
