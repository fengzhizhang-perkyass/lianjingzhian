from pathlib import Path
import zipfile,hashlib,json
R=Path(r'E:\网安比赛\report_workspace')
source=R.parent/'作品报告成品/Web3轻量化反洗钱智能分析系统_作品报告_图表优化版.docx'
target=source.with_name('Web3轻量化反洗钱智能分析系统_作品报告_图表精修版.docx')
replacements={hashlib.sha256(p.read_bytes()).hexdigest():R/'figures_readable'/p.name for p in (R/'figures').glob('*.png')}
changed=[]
with zipfile.ZipFile(source) as zin,zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as zout:
 for item in zin.infolist():
  data=zin.read(item.filename)
  match=replacements.get(hashlib.sha256(data).hexdigest()) if item.filename.startswith('word/media/') else None
  if match:data=match.read_bytes();changed.append(match.name)
  zout.writestr(item,data)
assert len(changed)==31
with zipfile.ZipFile(source) as a,zipfile.ZipFile(target) as b:
 assert all(a.read(n)==b.read(n) for n in a.namelist() if not n.startswith('word/media/'))
Q=R/'qa/typography_revision'
(Q/'asset_integrity.json').write_text(json.dumps({'target':str(target),'replaced_figures':changed,'unchanged_document_xml':True,'unchanged_screenshots':8,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
print('Final figure assets embedded; text and layout preserved.')
