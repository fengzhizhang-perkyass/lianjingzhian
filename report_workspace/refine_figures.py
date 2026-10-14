"""Report diagrams: pastel research schematics inspired by the supplied reference.
All labels and measurements are drawn from the saved manuscript; no new results.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import ast, math

R=Path(__file__).parent
OUT=R/'figures_readable'; OUT.mkdir(exist_ok=True)
INK='#18252F'; GRAY='#394954'; BLUE='#315D83'; TEAL='#326F65'; PURPLE='#555D79'; ORANGE='#896A3D'
PALE=['#CFDFEE','#D1E3DC','#DCDDE8','#EBDFC9']; COL=[BLUE,TEAL,PURPLE,ORANGE]
REG='C:/Windows/Fonts/msyh.ttc'; BOLD='C:/Windows/Fonts/simhei.ttf'
# About 20% larger lettering, with explicit width fitting inside nodes.
def font(n,b=False):return ImageFont.truetype(BOLD if b else REG,round(n))

def canvas(h=900):
 im=Image.new('RGB',(1800,h),'white');return im,ImageDraw.Draw(im)

def text_size(n):return round(n*1.20)
def fitted(s,n,b,maxw):
 nn=text_size(n)
 while nn>n and max(font(nn,b).getlength(t) for t in s.split('\n'))>maxw:nn-=1
 return nn

def rawtxt(d,x,y,s,n,c=INK,b=False,anchor='mm'):
 d.text((x,y),s.replace('−','-'),font=font(n,b),fill=c,anchor=anchor)

def txt(d,x,y,s,n=34,c=INK,b=False,anchor='mm'):
 maxw=2*min(x-18,1782-x) if anchor=='mm' else (1782-x if anchor=='lm' else x-18)
 nn=fitted(s,n,b,maxw)
 rawtxt(d,x,y,s,nn,c,b,anchor)

def multiline(d,x,y,s,n=32,c=INK,b=False,gap=47,maxw=None):
 ss=s.split('\n');nn=fitted(s,n,b,maxw or 2*min(x-18,1782-x))
 gap=max(gap,nn+7)
 for i,st in enumerate(ss):rawtxt(d,x,y+(i-(len(ss)-1)/2)*gap,st,nn,c,b)

def line(d,pts,c=INK,w=3,dash=False):
 if not dash:d.line(pts,fill=c,width=w,joint='curve');return
 for a,b in zip(pts,pts[1:]):
  ll=math.dist(a,b)
  for j in range(0,int(ll),17):
   p=(a[0]+(b[0]-a[0])*j/ll,a[1]+(b[1]-a[1])*j/ll)
   q=(a[0]+(b[0]-a[0])*min(j+9,ll)/ll,a[1]+(b[1]-a[1])*min(j+9,ll)/ll)
   d.line([p,q],fill=c,width=w)
def arr(d,pts,c=INK,w=3,dash=False):
 line(d,pts,c,w,dash);a,z=pts[-2:];ang=math.atan2(z[1]-a[1],z[0]-a[0]);L=15
 d.polygon([z,(z[0]-L*math.cos(ang-.45),z[1]-L*math.sin(ang-.45)),(z[0]-L*math.cos(ang+.45),z[1]-L*math.sin(ang+.45))],fill=c)
def region(d,r,title,k=0):
 d.rounded_rectangle(r,5,fill=PALE[k],outline=COL[k],width=1)
 nn=fitted(title,36,True,r[2]-r[0]-48)
 rawtxt(d,r[0]+24,r[1]+33,title,nn,INK,True,'lm')

def node(d,r,label,k=0,body='',fill=None,n=34):
 x,y,z,b=r;d.rounded_rectangle(r,3,fill=fill or 'white',outline=COL[k],width=3)
 ww=z-x-32;hh=b-y
 if body:
  nn=fitted(label,n,True,ww)
  rawtxt(d,(x+z)/2,y+hh*(.23 if '\n' in body else .29),label,nn,INK,True)
  multiline(d,(x+z)/2,y+hh*(.66 if '\n' in body else .70),body,29,GRAY,gap=39,maxw=ww)
 else:multiline(d,(x+z)/2,(y+b)/2,label,n,gap=46,maxw=ww)

def diamond(d,c,w,h,s,k=3):
 x,y=c;d.polygon([(x,y-h/2),(x+w/2,y),(x,y+h/2),(x-w/2,y)],fill=PALE[k],outline=COL[k],width=3)
 multiline(d,x,y,s,30,gap=43,maxw=w*.74)
def foot(d,h,s):txt(d,900,h-30,s,27,GRAY)
def save(im,name):im.save(OUT/(name+'.png'),dpi=(300,300))

def vector(d,x,y,w,n,k):
 for i in range(n):d.rectangle((x+i*w/n,y,x+(i+1)*w/n-4,y+38),fill=COL[k] if i%3==0 else PALE[k],outline=COL[k],width=1)
def graph(d,pts,edges,highlight=(),r=15):
 for a,b in edges:
  p,q=pts[a],pts[b];ll=math.dist(p,q)
  arr(d,[(p[0]+(q[0]-p[0])*r/ll,p[1]+(q[1]-p[1])*r/ll),(q[0]-(q[0]-p[0])*(r+6)/ll,q[1]-(q[1]-p[1])*(r+6)/ll)],'#667C8C',3)
 for i,(x,y) in enumerate(pts):d.ellipse((x-r,y-r,x+r,y+r),fill=TEAL if i in highlight else '#8DA9BF',outline='white',width=2)

# Recover the existing, evidence-checked labels without executing the old artist.
specs={}
tree=ast.parse((R/'revisions/before_visual_update/make_figures.py').read_text(encoding='utf-8'))
for st in tree.body:
 if isinstance(st,ast.Expr) and isinstance(st.value,ast.Call) and isinstance(st.value.func,ast.Name) and st.value.func.id=='flow':
  a=[ast.literal_eval(v) for v in st.value.args];kw={v.arg:ast.literal_eval(v.value) for v in st.value.keywords}
  specs[a[0]]=(a[1],a[2] if len(a)>2 else kw.get('foot',''))

def generic(name,rows,footer):
 parallel=name in {'background','policy','alignment','deviation','testing','long_scope','innovation_loop','audit'}
 h=140+len(rows)*300+(55 if footer else 0);im,d=canvas(h)
 for ri,row in enumerate(rows):
  y=50+ri*300;n=len(row);w=(1640-(n-1)*65)/n
  for ci,(title,body) in enumerate(row):
   x=80+ci*(w+65);k=ci%3
   region(d,(x,y,x+w,y+240),title,k)
   multiline(d,x+w/2,y+150,body,31,INK,gap=48,maxw=w-36)
   if not parallel and ci<n-1:arr(d,[(x+w+3,y+126),(x+w+62,y+126)])
  if ri<len(rows)-1 and name not in {'policy','testing','audit'}:
   if parallel and len(rows[ri+1])==n:
    for ci in range(n):
     cx=80+ci*(w+65)+w/2;arr(d,[(cx,y+240),(cx,y+296)])
   elif parallel:
    for ci in range(n):
     cx=80+ci*(w+65)+w/2;line(d,[(cx,y+240),(cx,y+266),(900,y+266)])
    arr(d,[(900,y+266),(900,y+296)])
   else:
    end=80+(n-1)*(w+65)+w/2;nn=len(rows[ri+1]);ww=(1640-(nn-1)*65)/nn
    arr(d,[(end,y+240),(end,y+270),(80+ww/2,y+270),(80+ww/2,y+296)])
 if footer:foot(d,h,footer)
 save(im,name)
for name,(rows,footer) in specs.items():generic(name,rows,footer)

def overview():
 h=1860;im,d=canvas(h)
 region(d,(30,20,1770,240),'用户交互与数据准备',3)
 node(d,(80,95,460,205),'分析人员输入',3,body='地址 / 节点ID / 搜索参数')
 node(d,(550,95,1090,205),'Streamlit 统一分析入口',3,body='预置案例 · 地址查询 · 报告下载')
 node(d,(1200,95,1720,205),'公开数据与冻结产物',3,body='特征 · 有向关系 · 模型 · 风险表')
 arr(d,[(460,150),(550,150)]);arr(d,[(1200,150),(1090,150)])
 region(d,(30,285,860,1070),'模块一  地址风险评分',0)
 region(d,(905,285,1770,1070),'模块二  风险引导关系追踪',1)
 node(d,(260,365,630,445),'地址特征与方向邻域',0)
 for x,lab in [(80,'行为画像\n51维'),(340,'方向偏离\n102维'),(600,'结构角色\n18维')]:
  node(d,(x,510,x+205,630),lab,0,n=31)
  arr(d,[(445,445),(445,478),(x+102,478),(x+102,510)])
 for x in [182,442,702]:line(d,[(x,630),(x,670),(445,670)])
 arr(d,[(445,670),(445,715)])
 node(d,(240,715,650,825),'171维联合 LightGBM',0,body='输出原始 margin')
 node(d,(80,890,415,985),'风险校准',0,body='综合分与等级')
 node(d,(470,890,805,985),'TreeSHAP 归因',0,body='实际模型的三组贡献')
 for cx in [248,638]:arr(d,[(445,825),(445,858),(cx,858),(cx,890)])
 node(d,(970,370,1290,465),'原始有向图',1)
 node(d,(1390,370,1710,465),'预计算风险表',1)
 node(d,(1010,540,1670,650),'风险锚点与反向可达索引',1,body='距离 + 正向 next-hop 见证')
 arr(d,[(1130,465),(1130,505),(1340,505),(1340,540)])
 arr(d,[(1550,465),(1550,505),(1340,505)])
 node(d,(1010,715,1670,825),'预算约束的候选路径搜索',1,body='沿出边扩展 · 低分连接需见证 · 防环')
 arr(d,[(1340,650),(1340,715)])
 node(d,(1010,890,1670,985),'覆盖重排与前缀折叠',1,body='完整路径 · 原分数 · 预算与停止原因')
 arr(d,[(1340,825),(1340,890)])
 # Explicit risk table transfer, routed between module rows without crossing boxes.
 arr(d,[(248,985),(248,1030),(885,1030),(885,480),(1550,480),(1550,465)],BLUE,3,True)
 txt(d,445,1060,'离线风险供给',27,BLUE)
 arr(d,[(820,205),(820,345),(445,345),(445,365)])
 arr(d,[(820,262),(1735,262),(1735,345),(1130,345),(1130,370)])
 region(d,(30,1120,1770,1650),'模块三  证据约束的可解释报告',2)
 node(d,(90,1210,485,1325),'冻结 Evidence',2,body='评分 + 归因 + 路径 + 版本')
 node(d,(595,1210,990,1325),'类型化事实目录',2,body='主体 · 类型 · 单位 · 源位置')
 node(d,(1100,1210,1695,1325),'LLM 生成六段结构化声明',2,body='仅选择事实与支持措辞')
 arr(d,[(485,1268),(595,1268)]);arr(d,[(990,1268),(1100,1268)])
 line(d,[(248,985),(248,1100),(60,1100)])
 line(d,[(638,985),(638,1100),(60,1100)])
 line(d,[(1340,985),(1340,1100),(60,1100)])
 arr(d,[(60,1100),(15,1100),(15,1268),(90,1268)])
 node(d,(1100,1400,1695,1530),'独立核验与有限局部修复',2,body='核验失败 → 最多一次修复 → 模板回退')
 node(d,(90,1400,990,1530),'源值渲染与可追溯审计',2,body='报告声明 → JSON Pointer → 特征行 / 路径段 / 原始记录')
 arr(d,[(1400,1325),(1400,1400)]);arr(d,[(1100,1465),(990,1465)])
 txt(d,900,1600,'统一证据契约：地址一致 · 版本一致 · 原风险不改写 · 输出来源可复核',31,PURPLE)
 region(d,(30,1700,1770,1800),'展示输出',3)
 txt(d,1080,1750,'风险与贡献  /  有向关系链  /  分析报告  /  来源定位与下载',32)
 arr(d,[(90,1465),(15,1465),(15,1670),(900,1670),(900,1700)])
 foot(d,h,'实线表示处理与证据传递；蓝色虚线表示离线风险产物供给')
 save(im,'system_overview')

def scoring():
 h=1430;im,d=canvas(h)
 node(d,(540,25,1260,110),'输入  地址行为特征与原始有向关系',0)
 for x in [310,900,1490]:arr(d,[(900,110),(900,153),(x,153),(x,200)])
 for x,title,body,k in [(50,'行为画像','地址自身的统计特征\n长尾变换与标准化',0),(640,'方向邻域偏离','上游与下游分别聚合\n相对均值与离散度',1),(1230,'有向结构角色','入度 / 出度 / 角色\n二步关系与局部统计',2)]:
  region(d,(x,200,x+520,610),title,k)
  if k==0:
   for i,v in enumerate([.35,.8,.55,.92,.43,.67]):d.rectangle((x+80+i*62,390-v*110,x+115+i*62,390),fill=BLUE)
  else:
   graph(d,[(x+100,330),(x+220,275),(x+260,380),(x+405,330)],[(0,1),(0,2),(1,3),(2,3)] if k==1 else [(0,2),(1,2),(2,3)],(2,))
  multiline(d,x+260,455,body,31,gap=46)
  vector(d,x+60,525,400,10,k);txt(d,x+260,588,['51 维','102 维（上游51 + 下游51）','18 维'][k],30,COL[k],True)
 for x in [310,900,1490]:line(d,[(x,610),(x,660),(900,660)])
 arr(d,[(900,660),(900,700)])
 node(d,(480,700,1320,800),'特征拼接  51 + 102 + 18 = 171 维',0,fill=PALE[0])
 arr(d,[(900,800),(900,850)])
 node(d,(510,850,1290,965),'联合 LightGBM 主模型',0,body='由同一模型产生最终 margin 与对应特征贡献')
 for x in [470,1330]:arr(d,[(900,965),(900,1010),(x,1010),(x,1060)])
 node(d,(80,1060,860,1175),'类别权重校正与温度校准',1,body='margin → 概率 → 0—100 综合风险')
 node(d,(940,1060,1720,1175),'原生 TreeSHAP 与三组归因',2,body='解释实际联合树 · 核对 margin 加和一致性')
 for x in [470,1330]:arr(d,[(x,1175),(x,1220),(900,1220),(900,1260)])
 node(d,(240,1260,1560,1350),'输出  风险分与等级 / 行为、偏离、结构贡献 / 版本信息',0,fill=PALE[0],n=32)
 foot(d,h,'三个单组诊断树仅辅助展示；诊断概率不参与综合分融合')
 save(im,'scoring')

def tracing():
 h=1510;im,d=canvas(h)
 region(d,(35,30,590,1390),'离线索引构建',0)
 node(d,(90,150,535,255),'预计算风险表 + 有向图',0)
 arr(d,[(312,255),(312,340)])
 node(d,(90,340,535,460),'选取风险锚点',0,body='默认分数 ≥ 30')
 arr(d,[(312,460),(312,550)])
 node(d,(90,550,535,675),'沿入边反向扩展',0,body='保存距离与真实 next-hop')
 arr(d,[(312,675),(312,790)])
 node(d,(90,790,535,910),'可达见证索引',0,body='正向连接序列可逐边核验')
 graph(d,[(150,1110),(260,1110),(370,1110),(485,1110)],[(0,1),(1,2),(2,3)],(3,),20)
 txt(d,312,1025,'索引逆向建立',31,BLUE,True)
 arr(d,[(475,1170),(160,1170)],BLUE,3,True)
 txt(d,312,1230,'返回路径保持原始方向',30)
 region(d,(640,30,1765,1390),'在线预算搜索与证据选路',1)
 node(d,(805,135,1580,235),'Seed + 深度 / 宽度 / 连续低分跨度 / 预算',1,n=30)
 arr(d,[(1192,235),(1192,310)])
 node(d,(875,310,1510,415),'沿原始出边读取候选节点',1)
 arr(d,[(1192,415),(1192,455)])
 diamond(d,(1192,550),440,190,'环路、深度或\n预算约束触发？')
 arr(d,[(1412,550),(1635,550),(1635,645)],ORANGE)
 node(d,(1470,645,1715,705),'停止 / 剪枝留痕',3,n=25)
 txt(d,1550,520,'是：停止并留痕',27,ORANGE)
 arr(d,[(1192,645),(1192,700)])
 txt(d,1230,673,'否',27,TEAL)
 diamond(d,(1192,790),440,180,'风险达锚点门槛？')
 node(d,(715,980,1155,1100),'核验低分连接见证',1,body='可达目标 / 真实边 / 跨度')
 node(d,(1270,980,1695,1100),'保留候选路径',1,body='完整节点序列与原风险')
 arr(d,[(970,790),(935,790),(935,980)]);txt(d,865,850,'否',29,GRAY)
 arr(d,[(1412,790),(1482,790),(1482,980)]);txt(d,1545,850,'是',29,TEAL)
 arr(d,[(535,850),(665,850),(665,1040),(715,1040)],BLUE,3,True)
 arr(d,[(1155,1040),(1270,1040)]);txt(d,1210,1000,'通过',27,TEAL)
 txt(d,928,1135,'不通过：剪枝并记录原因',27,ORANGE)
 node(d,(825,1200,1575,1320),'按新增覆盖重排并折叠严格前缀',1,body='选出 Top-K 完整路径；输出预算与停止原因')
 arr(d,[(1482,1100),(1482,1155),(1200,1155),(1200,1200)])
 # The next-depth continuation is explicitly bounded.
 arr(d,[(1695,1040),(1732,1040),(1732,362),(1510,362)],TEAL,3,True)
 txt(d,1588,278,'未达停止条件时继续',26,TEAL)
 foot(d,h,'低分节点被保留只说明存在连接见证，不改变模型评分，也不等同于非法认定')
 save(im,'tracing')

def reporting():
 h=1540;im,d=canvas(h)
 region(d,(30,25,1770,365),'输入与事实约束',0)
 node(d,(85,120,500,255),'冻结 Evidence',0,body='评分 / 归因 / 路径 / 版本')
 node(d,(620,105,1130,280),'类型化事实目录',0,body='类型、主体、单位、源值\n稳定 fact_id 与 Pointer')
 node(d,(1210,105,1750,280),'来源一致性核验',0,body='Seed、版本、路径与原分\n不合格输入直接拒绝')
 arr(d,[(500,185),(620,185)]);arr(d,[(1130,185),(1210,185)])
 txt(d,900,320,'事实目录提供可用事实；语言模型仅组织声明与表达',31,BLUE)
 region(d,(30,410,1770,1210),'声明生成与有限纠错',2)
 node(d,(160,495,745,610),'LLM 生成六段结构化声明',2,body='事实引用 + 支持措辞；禁止改写源值')
 arr(d,[(1480,280),(1480,385),(450,385),(450,495)])
 node(d,(160,705,745,830),'独立协议核验器',2,body='结构 / 引用 / 类型 / 主体 / 单位')
 arr(d,[(450,610),(450,705)])
 diamond(d,(450,1010),430,190,'候选声明通过？',2)
 arr(d,[(450,830),(450,915)])
 node(d,(970,705,1660,830),'仅修复失败位置，最多一次',3,body='保留正确声明；修复后再次独立核验')
 arr(d,[(665,1010),(865,1010),(865,767),(970,767)],ORANGE)
 txt(d,787,974,'否',29,ORANGE)
 node(d,(970,970,1660,1100),'模板回退与核心事实补全',3,body='API 失败 / 未配置 / 修复仍不合格')
 arr(d,[(1315,830),(1315,970)],ORANGE);txt(d,1460,900,'仍失败',28,ORANGE)
 arr(d,[(1660,765),(1720,765),(1720,1180),(600,1180),(600,1310)],TEAL,3,True)
 txt(d,1510,1150,'修复通过',28,TEAL)
 arr(d,[(745,550),(1760,550),(1760,1035),(1660,1035)],ORANGE,3,True)
 txt(d,1480,512,'API 失败 / 未配置时回退',27,ORANGE)
 region(d,(30,1240,1770,1460),'输出与证据追溯',1)
 node(d,(100,1310,825,1415),'源值渲染报告',1,body='报告数字由程序从冻结事实回填')
 node(d,(955,1310,1700,1415),'证据定位与审计包',1,body='JSON Pointer → 特征行 / 路径段 / 原记录')
 arr(d,[(450,1105),(450,1310)]);txt(d,492,1160,'是',29,TEAL)
 arr(d,[(1315,1100),(1315,1225),(820,1225),(820,1310)])
 arr(d,[(825,1360),(955,1360)])
 foot(d,h,'虚线表示条件分支；LLM、局部修复与模板回退均记录实际来源')
 save(im,'reporting')

overview();scoring();tracing();reporting()

# Data graphics: real axes and restrained marks; values and populations unchanged.
def barplot(name,labels,values,maxv,dec,footer):
 h=170+len(labels)*105;im,d=canvas(h);x0=540;w=980;top=55;bottom=h-110
 for j in range(6):
  x=x0+w*j/5;line(d,[(x,top),(x,bottom)],'#E2E6E9',2);txt(d,x,bottom+30,f'{maxv*j/5:g}',26,GRAY)
 for i,(label,v) in enumerate(zip(labels,values)):
  y=top+35+i*105;txt(d,x0-35,y,label,32,INK,False,'rm')
  d.rectangle((x0,y-21,x0+w*v/maxv,y+21),fill=TEAL if i==0 else '#9BB3CB')
  txt(d,x0+w*v/maxv+18,y,f'{v:.{dec}f}',30,INK,True,'lm')
 foot(d,h,footer);save(im,name)
barplot('ablation',['完整联合模型','去行为画像','去邻域偏离','去有向结构','去边方向并重算'],[.5429238,.4799217,.2829463,.5114441,.3444706],.6,4,'Average Precision；相同 compact 预算下重新训练与校准')
barplot('topk',['Top-100 · 100/100','Top-500 · 488/500','Top-1% · 545/565','Top-5% · 1232/2822'],[100,97.6,96.46,43.66],100,2,'命中率 %；仅限已知标签测试候选，不表示全图准确率')
barplot('report_faults',['当前类型协议','旧引用规则'],[120,24],120,0,'拒绝的人为故障数 / 120；不表示自然大模型幻觉率')

im,d=canvas(750)
for i,(title,a,b,mx) in enumerate([('预测锚点累计',5,23,30),('唯一边累计',5,59,60),('非空起点数',4,17,20)]):
 x=80+i*585;txt(d,x+260,65,title,36,INK,True)
 ticks=4 if mx!=20 else 5
 for j in range(ticks):
  yy=590-j*400/(ticks-1);line(d,[(x+50,yy),(x+495,yy)],'#E3E7EB',2);txt(d,x+36,yy,f'{mx*j/(ticks-1):g}',25,GRAY,False,'rm')
 for xx,v,c in [(x+110,a,'#AEC0D2'),(x+315,b,TEAL)]:
  hh=400*v/mx;d.rectangle((xx,590-hh,xx+110,590),fill=c);txt(d,xx+55,565-hh,str(v),34,INK,True)
 txt(d,x+165,630,'原 Beam',29);txt(d,x+370,630,'当前方案',29)
foot(d,750,'同一 72 个起点；锚点和边逐起点去重后累计，非全图唯一总数');save(im,'tracing_gain')

# Keep two-dimensional experimental structure, with denominator in every cell.
im,d=canvas(880);txt(d,960,55,'预测标签',34,INK,True)
for j,s in enumerate(['合法','非法']):txt(d,785+j*430,125,s,33)
for i,s in enumerate(['真实合法','真实非法']):txt(d,360,290+i*230,s,33)
for i,row in enumerate([[53729,159],[1516,1032]]):
 for j,v in enumerate(row):
  x=590+j*430;y=185+i*230;d.rectangle((x,y,x+390,y+200),fill='#D1E3DC' if i==j else '#EBDFC9')
  txt(d,x+195,y+78,f'{v:,}',54,TEAL if i==j else ORANGE,True)
  txt(d,x+195,y+143,['真负例','假正例','假负例','真正例'][i*2+j],29,GRAY)
foot(d,880,'已知测试地址 56,436；分类评估阈值约 27.9512 分');save(im,'confusion')

def support_diagrams():
 # Explicit neighborhood directions and a shared target, rather than three cards.
 im,d=canvas(810)
 region(d,(45,45,630,475),'上游邻域',0);region(d,(1170,45,1755,475),'下游邻域',1)
 pts=[(220,190),(220,355),(510,275),(900,275),(1280,275),(1590,190),(1590,355)]
 graph(d,pts,[(0,2),(1,2),(2,3),(3,4),(4,5),(4,6)],(3,),24)
 txt(d,900,205,'目标地址 v',37,INK,True);txt(d,900,350,'行为向量 x(v)',32)
 txt(d,335,420,'上游均值与标准差',32,BLUE);txt(d,1465,420,'下游均值与标准差',32,TEAL)
 node(d,(90,570,800,690),'上游偏离 51 维',0,body='目标减上游均值，按上游离散度标准化')
 node(d,(1000,570,1710,690),'下游偏离 51 维',1,body='目标减下游均值，按下游离散度标准化')
 arr(d,[(335,475),(335,530),(445,530),(445,570)],BLUE)
 arr(d,[(1465,475),(1465,530),(1355,530),(1355,570)],TEAL)
 for x in [445,1355]:arr(d,[(900,380),(900,515),(x,515),(x,570)])
 foot(d,810,'标准差下限 0.5；裁剪至 ±8；无邻居时偏离记零，并保留结构背景');save(im,'deviation')
 # Structural role panels use real directed motifs.
 im,d=canvas(580)
 for k,title in enumerate(['汇入关系','分出关系','中间连接']):
  x=40+k*595;region(d,(x,35,x+535,475),title,k)
  pts=[(x+100,190),(x+100,340),(x+295,270),(x+455,270)]
  ed=[(0,2),(1,2),(3,2)] if k==0 else ([(2,0),(2,1),(2,3)] if k==1 else [(0,2),(1,2),(2,3)])
  graph(d,pts,ed,(2,),22);txt(d,x+268,425,['多个地址指向目标','目标指向多个地址','连接上下游地址'][k],31)
 foot(d,580,'结构角色由有向关系定义，不代表金额大小或非法标签');save(im,'roles')
 # Show actual overlap using graph paths, then one compact result.
 im,d=canvas(790);region(d,(40,35,800,635),'候选路径中的严格前缀',0)
 for i,labels in enumerate(['AB','ABC','ABCD']):
  yy=205+i*150;pts=[(150+j*170,yy) for j in range(len(labels))];graph(d,pts,[(j,j+1) for j in range(len(labels)-1)],(),22)
  for p,label in zip(pts,labels):txt(d,p[0],p[1]+46,label,28)
 arr(d,[(820,340),(955,340)])
 region(d,(980,35,1760,635),'折叠前缀与新增覆盖重排',1)
 txt(d,1370,180,'优先保留最大完整序列',33,TEAL,True)
 pts=[(1070+i*190,320) for i in range(4)];graph(d,pts,[(0,1),(1,2),(2,3)],(3,),22)
 for p,label in zip(pts,'ABCD'):txt(d,p[0],p[1]+48,label,28)
 txt(d,1370,455,'默认案例',30,GRAY)
 txt(d,1370,520,'4 条路径 / 4 边 → 3 条路径 / 7 边',33,TEAL,True)
 foot(d,790,'左侧序列为机制示意；默认案例的数字来自已保存运行结果');save(im,'coverage')
 # File dependencies, distinct from a sequential processing chart.
 im,d=canvas(860);region(d,(50,40,1750,755),'一次运行的独立审计目录',2)
 entries=[(100,145,540,285,'冻结来源','evidence.json\nfact_catalog.json'),(680,145,1120,285,'生成与核验','claims_raw.json\nclaims_validated.json'),(1260,145,1700,285,'审核与输出','audit.json\nreport.md')]
 for x,y,z,b,ti,bo in entries:node(d,(x,y,z,b),ti,2,body=bo,n=32)
 arr(d,[(540,215),(680,215)]);arr(d,[(1120,215),(1260,215)])
 node(d,(400,470,1400,625),'manifest.json',2,body='文件摘要、运行版本与本地一致性核对')
 for x in [320,900,1480]:arr(d,[(x,285),(x,390),(900,390),(900,470)],PURPLE,3,True)
 foot(d,860,'每次运行独立保存；哈希用于本地一致性检查；不保存 API 密钥');save(im,'audit')
 # Dataset distribution and proportional time split.
 im,d=canvas(940);txt(d,85,55,'全图标签组成',38,INK,True,'lm')
 vals=[251088,14266,557588];cols=[BLUE,ORANGE,'#B9C2CD'];x=85
 for v,c in zip(vals,cols):
  ww=1630*v/sum(vals);d.rectangle((x,140,x+ww,255),fill=c);x+=ww
 for i,(label,c) in enumerate(zip(['已知合法 251,088','已知非法 14,266','未知 557,588'],cols)):
  x=85+560*i;d.ellipse((x,300,x+22,322),fill=c);txt(d,x+40,311,label,31,INK,False,'lm')
 txt(d,85,445,'已知标签的时间划分',38,INK,True,'lm')
 x=85
 for v,c,ti,cut in [(170404,BLUE,'训练',34),(38514,TEAL,'验证',41),(56436,PURPLE,'测试',49)]:
  ww=1630*v/265354;d.rectangle((x,530,x+ww-5,625),fill=c)
  txt(d,x+ww/2,576,ti,33,'white',True);txt(d,x+ww/2,675,f'{v:,}',32,c,True);txt(d,x+ww/2,730,f'截止时段 {cut}',28,GRAY);x+=ww
 foot(d,940,'unknown 不进入监督损失，但可参与无标签图结构与推理');save(im,'dataset')
 # Four mechanism diagrams with distinct topology and a shared graph legend.
 im,d=canvas(1070)
 configurations=[('低分连接','低分中间节点后存在目标',[(70,200),(250,200),(430,200),(610,200)],[(0,1),(1,2),(2,3)],(3,)),('高连接噪声','多条分支中保留真实入口',[(70,240),(240,160),(240,240),(240,320),(420,320),(610,320),(430,160)],[(0,1),(0,2),(0,3),(3,4),(4,5),(1,6)],(5,)),('循环与死端','拒绝回环与无目标分支',[(70,230),(240,230),(240,340),(430,230),(610,230),(430,340)],[(0,1),(1,2),(2,0),(1,3),(3,4),(3,5)],(4,)),('平行分支','在有限名额下选择新增覆盖',[(70,240),(285,120),(285,200),(285,280),(285,360),(610,120),(610,200),(610,280),(610,360)],[(0,i) for i in range(1,5)]+[(i,i+4) for i in range(1,5)],(5,6,7,8))]
 for k,(ti,desc,pts,eds,hl) in enumerate(configurations):
  x=45+k%2*880;y=35+k//2*480;region(d,(x,y,x+830,y+445),ti,k%3)
  graph(d,[(x+px+35,y+py) for px,py in pts],eds,hl,18);txt(d,x+415,y+410,desc,29)
 foot(d,1070,'每类 12 个固定种子实例，共 48 图；绿色为目标，示意结构不是真实 AML 路径标签');save(im,'mechanisms')

support_diagrams()
print('Redesigned diagrams and charts:',len(list(OUT.glob('*.png'))))
