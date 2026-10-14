from pathlib import Path
from PIL import Image,ImageChops,ImageDraw
from pypdf import PdfReader
import json
R=Path(r'E:\网安比赛\report_workspace');Q=R/'qa/typography_revision';O=R/'qa/visual_revision/final'
a,b=PdfReader(O/'report.pdf'),PdfReader(Q/'report.pdf')
assert len(a.pages)==len(b.pages)==68
assert [p.extract_text() for p in a.pages]==[p.extract_text() for p in b.pages]
changed=[];unchanged=[]
for p in sorted(Q.glob('page-*.png')):
 old=Image.open(O/p.name).convert('RGB');new=Image.open(p).convert('RGB')
 (changed if old.size!=new.size or ImageChops.difference(old,new).getbbox() else unchanged).append(p)
for k in range(0,len(changed),4):
 group=changed[k:k+4];sheet=Image.new('RGB',(1840,2670),'#D1D1D1');d=ImageDraw.Draw(sheet)
 for j,p in enumerate(group):
  x=j%2*930;y=j//2*1335;d.text((x+8,y+5),p.stem,fill='black');sheet.paste(Image.open(p),(x,y+30))
 sheet.save(Q/f'review-{k//4:02}.jpg',quality=94)
(Q/'pagination_check.json').write_text(json.dumps({'pages':68,'pdf_text_unchanged':True,'changed':[p.stem for p in changed],'unchanged':[p.stem for p in unchanged]},indent=2),encoding='utf-8')
print('Changed pages',len(changed),[p.stem for p in changed]);print('Pixel-identical pages',len(unchanged))
