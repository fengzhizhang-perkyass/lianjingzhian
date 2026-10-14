"""Public metadata research for module-two planning; does not alter the Demo."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import re
import xml.etree.ElementTree as ET
import requests


def main():
    folder = Path(__file__).resolve().parents[1] / 'artifacts/experiments/tracing_v2_planning/literature'
    folder.mkdir(parents=True, exist_ok=True)
    fetched = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    query = '(ti:"Diverse Beam Search") OR (all:blockchain AND all:"tracing")'
    response = requests.get('https://export.arxiv.org/api/query', params={
        'search_query': query, 'max_results': 20, 'sortBy': 'relevance'}, timeout=35)
    response.raise_for_status()
    (folder / 'arxiv.xml').write_text(response.text, encoding='utf-8')
    ns = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
    papers = []
    for entry in ET.fromstring(response.text).findall('a:entry', ns):
        def value(path):
            item = entry.find(path, ns)
            return ' '.join(item.text.split()) if item is not None and item.text else None
        identifier = re.sub(r'v\d+$', '', value('a:id').split('/')[-1])
        papers.append({'title': value('a:title'), 'authors': [a.find('a:name', ns).text for a in entry.findall('a:author', ns)],
                       'year': int(value('a:published')[:4]), 'publication_date': value('a:published')[:10],
                       'venue': value('x:journal_ref'), 'comment': value('x:comment'), 'doi': value('x:doi'),
                       'arxiv_id': identifier, 'abstract': value('a:summary'), 'citation_count': None,
                       'full_text_status': 'open_pdf', 'pdf_url': f'https://arxiv.org/pdf/{identifier}',
                       'download_status': 'not_requested', 'code_url': None, 'source_platforms': ['arxiv'], 'fetched_at': fetched})
    titles = [
        'The use of MMR diversity-based reranking for reordering documents and producing summaries',
        'Cost-effective outbreak detection in networks',
        'Local graph partitioning using PageRank vectors',
    ]
    scans = []
    for i, title in enumerate(titles):
        result = requests.get('https://api.crossref.org/works', params={'query.bibliographic': title, 'rows': 3}, timeout=35)
        result.raise_for_status()
        raw = result.json()
        (folder / f'crossref_{i}.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
        for item in raw['message']['items']:
            year = item.get('published', item.get('issued', {})).get('date-parts', [[None]])[0][0]
            scans.append({'title': item.get('title', [''])[0], 'authors': [' '.join(filter(None, [a.get('given'), a.get('family')])) for a in item.get('author', [])],
                          'year': year, 'publication_type': item.get('type'), 'venue': item.get('container-title', [None])[0] if item.get('container-title') else None,
                          'doi': item.get('DOI'), 'arxiv_id': None, 'abstract': item.get('abstract'), 'citation_count': None,
                          'full_text_status': 'unknown', 'pdf_url': None, 'download_status': 'not_requested',
                          'code_url': None, 'source_platforms': ['crossref'], 'fetched_at': fetched, 'discovery_query': title})
    (folder / 'papers.json').write_text(json.dumps(papers + scans, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{k: p.get(k) for k in ['title', 'year', 'venue', 'doi', 'arxiv_id', 'comment']} for p in papers + scans], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
