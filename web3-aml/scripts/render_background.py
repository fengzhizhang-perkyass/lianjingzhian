"""Render local marketing content to static HTML. No runtime fetch/build is needed."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- project-background:start -->'
END = '<!-- project-background:end -->'


def render():
    content = json.loads((ROOT / 'frontend/content/project-background.json').read_text())
    esc = lambda value: html.escape(str(value), quote=True)
    stats = ''.join(
        f'<article class="background-stat"><span class="background-stat-tag">{esc(s["tag"])}</span>'
        f'<p class="background-stat-number"><strong>{esc(s["value"])}</strong><span>{esc(s["unit"])}</span></p>'
        f'<p class="background-stat-label">{esc(s["label"])}</p></article>'
        for s in content['statistics'])
    cards = ''.join(
        f'<article class="policy-card"><div class="policy-card-top"><span>{esc(p["angle"])}</span><small>{esc(p["date"])}</small></div>'
        f'<h3>{esc(p["title"])}</h3><p>{esc(p["summary"])}</p><footer>{esc(p["publisher"])}</footer></article>'
        for p in content['policies'])
    return (f'{START}\n<section class="project-background" id="background" aria-labelledby="background-title">'
            '<div class="background-inner"><div class="background-heading"><div><span class="section-index">01 / 项目背景</span>'
            f'<h2 id="background-title" tabindex="-1">{esc(content["title"][0])}<br><span>{esc(content["title"][1])}</span></h2></div>'
            f'<p>{esc(content["intro"])}</p></div><div class="background-statistics">{stats}</div>'
            f'<div class="background-policies">{cards}</div><div class="background-closing"><p>{esc(content["closing"])}</p>'
            '<a class="hero-link" href="/#path">了解技术路径 <span aria-hidden="true">↓</span></a></div></div></section>\n'
            f'{END}')


if __name__ == '__main__':
    target = ROOT / 'frontend/index.html'
    source = target.read_text()
    if START in source:
        before, rest = source.split(START, 1)
        _, after = rest.split(END, 1)
        updated = before + render() + after
    else:
        marker = '    <section class="landing-technology"'
        assert marker in source
        updated = source.replace(marker, render() + '\n' + marker, 1)
    target.write_text(updated)
    print('Project background rendered from local JSON.')
