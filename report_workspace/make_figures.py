from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

ROOT=Path(__file__).parent
OUT=ROOT/'figures'; OUT.mkdir(exist_ok=True)
FONT='C:/Windows/Fonts/simhei.ttf'
BLUE='#245D92'; TEAL='#168C8C'; GOLD='#C6852F'; INK='#203047'; GRAY='#5B6878'
def f(n):return ImageFont.truetype(FONT,n)
def new(h=900):
 im=Image.new('RGB',(1800,h),'white');return im,ImageDraw.Draw(im)
def text(d,xy,s,size=36,fill=INK,anchor=None):d.text(xy,s.replace('−','-'),font=f(size),fill=fill,anchor=anchor)
def lines(d,x,y,ss,size=33,fill=GRAY,gap=48):
 for i,s in enumerate(ss.split('\n')):text(d,(x,y+i*gap),s,size,fill)
def arrow(d,a,b,color='#7890A8',width=6):
 d.line([a,b],fill=color,width=width)
 ang=math.atan2(b[1]-a[1],b[0]-a[0]);L=18
 pts=[b,(b[0]-L*math.cos(ang-.48),b[1]-L*math.sin(ang-.48)),(b[0]-L*math.cos(ang+.48),b[1]-L*math.sin(ang+.48))]
 d.polygon(pts,fill=color)
def icon(d,x,y,k,c=BLUE):
 if k=='db':
  d.rectangle((x,y+13,x+68,y+59),fill=c);d.ellipse((x,y,x+68,y+25),fill=c);d.arc((x,y+44,x+68,y+69),0,180,fill=c,width=6)
  d.arc((x+2,y+18,x+66,y+43),0,180,fill='white',width=2)
 elif k=='graph':
  pts=[(x+7,y+18),(x+57,y+5),(x+63,y+59),(x+18,y+63)]
  for a,b in [(0,1),(0,3),(1,2),(3,2)]:d.line([pts[a],pts[b]],fill=c,width=5)
  for a,b in pts:d.ellipse((a-9,b-9,a+9,b+9),fill=c)
 elif k=='report':
  d.rounded_rectangle((x+8,y,x+61,y+72),radius=5,outline=c,width=5)
  for a in [20,34,48]:d.line((x+20,y+a,x+48,y+a),fill=c,width=4)
 else:
  d.polygon([(x+34,y),(x+65,y+12),(x+59,y+47),(x+34,y+72),(x+8,y+47),(x+2,y+12)],outline=c,width=5)
  d.line([(x+17,y+32),(x+29,y+43),(x+50,y+23)],fill=c,width=5)
def box(d,x,y,w,h,title,body='',color=BLUE,idx='',iso=False,kind='graph'):
 if iso:
  d.polygon([(x,y),(x+20,y-20),(x+w+20,y-20),(x+w,y)],fill='#E7EEF7')
  d.polygon([(x+w,y),(x+w+20,y-20),(x+w+20,y+h-20),(x+w,y+h)],fill='#CDDCEB')
 d.rounded_rectangle((x,y,x+w,y+h),radius=18,fill='#F6F9FC',outline='#C7D5E3',width=3)
 d.rounded_rectangle((x,y,x+9,y+h),radius=3,fill=color)
 icon(d,x+24,y+26,kind,color)
 text(d,(x+110,y+31),title,39,color)
 lines(d,x+28,y+110,body,30,gap=40)
 if idx:text(d,(x+w-32,y+h-30),idx,25,'#8D9CB0',anchor='mm')
def save(im,name):im.save(OUT/(name+'.png'),dpi=(240,240))
def flow(name,rows,foot='',iso=False):
 # each row is list of (title,body); left-to-right then down
 h=150+len(rows)*310+(75 if foot else 0);im,d=new(h)
 colors=[BLUE,TEAL,GOLD]
 for ri,row in enumerate(rows):
  n=len(row);w=(1640-(n-1)*55)/n;x0=80;y=70+ri*310
  for ci,(ti,bo) in enumerate(row):
   x=x0+ci*(w+55);box(d,x,y,w,235,ti,bo,colors[ci%3],iso=iso,kind=['db','graph','report'][ci%3])
   if ci<n-1 and name not in {'alignment','scoring','deviation','policy','long_scope','testing'}:
    arrow(d,(x+w+8,y+117),(x+w+47,y+117))
  if ri<len(rows)-1:
   if name=='alignment':
    for cx in [335,900,1465]:arrow(d,(cx,y+239),(cx,y+286))
   elif name=='scoring':
    if ri==0:
     for cx in [335,900,1465]:arrow(d,(cx,y+239),(cx,y+286))
    else:
     for cx in [475,1325]:arrow(d,(cx,y+239),(cx,y+286))
   elif name=='deviation':
    for cx in [475,1325]:arrow(d,(cx,y+239),(cx,y+300))
   elif name in {'policy','testing'}:pass
   elif name in {'case_wuhan','reporting'}:
    endx=80+(n-1)*(w+55)+w/2
    nn=len(rows[ri+1]);ww=(1640-(nn-1)*55)/nn;nextx=80+ww/2
    d.line([(endx,y+239),(endx,y+266),(nextx,y+266)],fill='#7890A8',width=5)
    arrow(d,(nextx,y+266),(nextx,y+293))
   else:arrow(d,(900,y+245),(900,y+295))
 if foot:text(d,(900,h-42),foot,30,GRAY,'mm')
 save(im,name)

flow('background',[[('风险优先级','海量地址 → 先看谁\n评分与实际模型证据'),('关系链组织','有向图 → 怎样连接\n目标、见证与预算'),('可审核解释','结构化事实 → 如何说明\n声明、核验与来源')]],'公开记录需要转化为可复核的分析线索',True)
flow('case_wuhan',[[('境外货款','通报所述资金入口'),('结汇账户','涉案公司相关账户'),('关联企业','配票与资金转账')],[('多轮流转','关系链条增加'),('资金池归集','形成资金回流'),('分析需求','5.9万条交易流水\n案件涉案金额20亿元')]],'公开通报机制重绘；不是本系统恢复的银行账户路径',True)
flow('case_bybit',[[('资产被盗','2025年2月21日前后\n通报金额约15亿美元'),('转换与分散','部分资产转为其他资产\n涉及多链与数千地址'),('研究启示','优先级 + 关系 + 证据\n本作品限定地址关系图')]],'来源：FBI IC3 2025年2月26日通报；示意图不还原逐笔交易',True)
flow('policy',[[('数字金融安全','2021年数字人民币白皮书\n隐私保护与反洗钱考虑'),('风险导向治理','反洗钱法2024年修订\n2025年1月1日起施行')],[('本作品技术回应','预测优先级与来源保留\n公开数据辅助分析'),('迁移条件','依法授权与重新评估\n未接入数字人民币系统')]],iso=True)
flow('alignment',[[('痛点一','个体与方向环境脱节'),('痛点二','低分节点截断关系'),('痛点三','引用存在但含义错误')],[('证据融合评分','行为 + 偏离 + 结构\n同预算消融与Top-K'),('可达见证追踪','真实连接 + 有限预算\n机制图与真实起点'),('类型约束报告','声明核验 + 精确定位\n故障注入与真实API')]],iso=True)
flow('architecture',[[('公开数据层','地址特征与标签\n原始有向关系')],[('评分模块','171维联合LightGBM\n校准风险与TreeSHAP'),('追踪模块','锚点索引与预算搜索\n路径、见证与边界'),('报告模块','事实目录与声明核验\n局部修复与审计')],[('统一交互层','Streamlit页面与预置案例\n风险 → 路径 → 来源 → 下载')]],'离线预计算和在线分析分离；模块间绑定同一数据与评分版本',True)
flow('data_pipeline',[[('字段适配','读取配置与检查列名\n特征 / 标签 / 有向边'),('统一地址','最新记录与ID映射\nunknown独立保留'),('构建产物','矩阵、掩码、双向邻接\n指纹与可复用缓存')]],iso=True)
flow('scoring',[[('行为画像 51维','本地址的统计背景\n长尾变换与标准化'),('方向偏离 102维','上游51 + 下游51\n相对均值与标准差'),('结构角色 18维','入出度、角色与二步关系\n不读取标签或风险')],[('联合LightGBM','171维特征直接输入\n一个主模型决定综合分')],[('类别权重与温度','校正margin → 概率\n输出0—100风险'),('联合TreeSHAP','实际主模型的贡献\n三组汇总与加和核对')]],'三个单组诊断树仅辅助展示；诊断概率不参与综合分',True)
flow('deviation',[[('上游邻居','指向目标地址\n计算均值与标准差'),('目标地址','51维行为值\n保持个体语境'),('下游邻居','目标地址指向\n计算均值与标准差')],[('上游偏离 51维','目标减上游均值\n按上游离散度标准化'),('下游偏离 51维','目标减下游均值\n按下游离散度标准化')]],'标准差下限0.5；裁剪±8；无邻居记零并保留结构背景')
flow('calibration',[[('原始margin','联合树输出 m\nTreeSHAP在此加和'),('权重校正','m − log(w+)\nw+ ≈ 17.2680'),('温度与概率','sigmoid(校正值 / T)\nT ≈ 0.9169；再乘100')]],'风险等级边界、评价分类阈值和搜索锚点门槛分别配置')
flow('tracing',[[('离线可达索引','从风险锚点反向搜索\n距离与真实next-hop'),('预算内候选搜索','读取原风险与有向关系\n低分连接必须有见证'),('证据选路','新增覆盖与重叠控制\n折叠严格前缀')],[('结构化追踪结果','完整路径 + 逐跳风险 + 连接理由\n预算 + 停止原因 + 版本 + 稳定ID')]],iso=True)
flow('anchor_index',[[('风险锚点集合','分数 ≥ 配置门槛\n默认30分'),('沿入边构建索引','保存到锚点距离\n记录正向next-hop'),('从Seed读取见证','沿原始出边还原路径\n核对深度、预算和环路')]],'索引反向构建，返回路径始终遵守原始有向关系',True)
flow('bridge',[[('低分连接节点','模型风险16.10\n分数保持不变'),('真实有向关系','连接见证由图验证\n保留路径理由'),('下游复核目标','模型风险61.02\n达到锚点门槛')]],'低分不代表已知合法；保留连接不等于认定非法',True)
flow('coverage',[[('候选存在重复','A→B\nA→B→C\nA→B→C→D'),('前缀折叠与重排','保留最大完整序列\n优先新增节点与边'),('默认案例结果','4路径 / 4唯一边 →\n3路径 / 7唯一边')]],'示意序列用于解释机制；右侧数字来自当前默认案例')
flow('reporting',[[('冻结Evidence','模块一评分与依据\n模块二路径与见证'),('类型事实目录','类型 / 主体 / 单位\n源值 / Pointer / 版本'),('LLM声明组织','固定六段JSON\n只选事实与支持措辞')],[('独立核验','结构、引用、类型和主体\n单位与真实来源'),('有限局部修复','保留正确声明\n最多一次失败位置修复'),('回填与审计','源值渲染与核心补全\n精确定位和下载包')]],'未配置或API失败时使用同协议模板；记录真实输出来源',True)
flow('typed_claim',[[('事实目录','类型：地址模型风险\n主体：目标地址\n单位：0—100分'),('声明匹配','fact_id对应真实事实\n类型、主体、单位一致\n不接收自由事实text'),('程序渲染','从源事实读取数字\n附证据编号与定位\nLLM不修改源值')]],iso=True)
flow('validation',[[('结构检查','六段、字段、唯一性\n长度与数值合法性'),('引用检查','事实ID存在\nPointer规范且可解析'),('含义检查','类型、主体、单位\n与所属段落相符')],[('来源检查','Seed与版本一致；路径无环且边真实\n风险保持冻结值；不合格Evidence直接拒绝')]])
flow('repair',[[('初次候选','正确声明 → 保留\n失败声明 → 定位'),('一次局部修复','仅允许原失败位置\n不改来源和正确内容'),('最终复验','失败部分模板回退\n补全必选事实并留痕')]],'修复结果与模板结果分别记录；不将回退冒充LLM成功')
flow('audit',[[('来源文件','evidence.json\nfact_catalog.json'),('生成与核验','claims_raw.json\nclaims_validated.json'),('审核与输出','audit.json / report.md\nmanifest.json')]],'每次运行独立目录；哈希用于本地一致性；不保存API密钥',True)
flow('testing',[[('机制与接口','48构造图\n数据、模型与版本测试'),('真实公开数据','评分测试与72追踪起点\n10真实Evidence'),('真实服务验收','1地址 / 2次报告\n网页定位与审计下载')],[('协议故障测试','120人为故障 + 12正确用例\n模拟修复120次 + 保留1200条正确声明')]],'不同测试层级分开报告，不将模拟修复转换成真实模型成功率')
flow('long_scope',[[('固定起点探索复测','72起点\n最长11跳\n非空17 → 19'),('精选能力案例','另选3个起点\n每条32跳 / 33地址\n逐边核查真实方向')]],'精选样例不进入72起点性能表；关系跳数不表示同一笔资金流转',True)
flow('innovation_loop',[[('创新一 风险感知','三类证据职责清楚\n解释实际联合模型'),('创新二 关系发现','跨低分断点与远距离\n保留原分和真实见证'),('创新三 审计解释','声明含义受类型约束\n核验、定位与局部修复')],[('共同证据接口','地址、分数、路径、Pointer与版本在模块间保持一致\n同一案例贯穿风险判断、关系复核与报告来源')]],iso=True)

def rolefig():
 im,d=new(720)
 for k,(title,c) in enumerate([('汇入关系',BLUE),('分出关系',TEAL),('中间连接',GOLD)]):
  cx=300+k*600;cy=330
  text(d,(cx,75),title,43,c,'mm')
  center=(cx,cy);pts=[(cx-170,cy-90),(cx-170,cy+90),(cx+170,cy)]
  for i,p in enumerate(pts):
   if k==0: a,b=p,center
   elif k==1:a,b=center,p
   else:a,b=(p,center) if i<2 else (center,p)
   dx=b[0]-a[0];dy=b[1]-a[1];ll=math.hypot(dx,dy)
   arrow(d,(a[0]+dx/ll*29,a[1]+dy/ll*29),(b[0]-dx/ll*32,b[1]-dy/ll*32),c)
  for x,y in [center]+pts:d.ellipse((x-26,y-26,x+26,y+26),fill=c if (x,y)==center else '#C5D5E5',outline='white',width=4)
 text(d,(900,620),'结构角色由有向关系定义，不代表金额大小或非法标签',33,GRAY,'mm');save(im,'roles')
rolefig()

def bars(name,labels,values,maxv=1,dec=4,foot='',color=BLUE,extra=None):
 h=160+len(labels)*102+110;im,d=new(h)
 x0=535;end=1510;width=end-x0
 for j in range(6):
  x=x0+width*j/5;d.line((x,70,x,h-125),fill='#E2E9F0',width=2)
  text(d,(x,42),f'{maxv*j/5:g}',25,GRAY,'mm')
 for i,(l,v) in enumerate(zip(labels,values)):
  y=90+i*102;text(d,(500,y+27),l,35,INK,'rm')
  w=max(3,width*v/maxv);d.rounded_rectangle((x0,y,x0+w,y+56),radius=8,fill=TEAL if i==0 else color)
  val=f'{v:.{dec}f}';text(d,(x0+w+18,y+26),val,32,INK,'lm')
 if foot:text(d,(900,h-42),foot,29,GRAY,'mm')
 save(im,name)
bars('ablation',['完整联合模型','去行为画像','去邻域偏离','去有向结构','去边方向并重算'],[.5429238,.4799217,.2829463,.5114441,.3444706],.6,foot='指标：Average Precision；相同compact预算下重新训练与校准')
bars('topk',['Top-100  100/100','Top-500  488/500','Top-1%  545/565','Top-5%  1232/2822'],[100,97.6,96.46,43.66],100,2,foot='仅限已知标签测试地址；百分比是候选命中率，不是全图准确率')
bars('report_faults',['类型协议拒绝故障','旧引用规则拒绝故障'],[120,24],120,0,foot='总计120个人为注入故障；不代表自然LLM幻觉率')

im,d=new(800)
for idx,(ti,a,b) in enumerate([('预测锚点累计',5,23),('唯一边累计',5,59),('非空起点数',4,17)]):
 x=100+idx*570;text(d,(x+250,65),ti,39,BLUE,'mm');mx=max(a,b)*1.15
 for j,(v,c,l) in enumerate([(a,'#9EAFBF','旧Beam'),(b,TEAL,'当前方案')]):
  xx=x+70+j*230;hh=450*v/mx;d.rounded_rectangle((xx,600-hh,xx+130,600),radius=8,fill=c)
  text(d,(xx+65,565-hh),str(v),43,INK,'mm');text(d,(xx+65,645),l,31,INK,'mm')
text(d,(900,755),'同一72起点；锚点和边为逐起点去重后累计，不是全局唯一总数',30,GRAY,'mm');save(im,'tracing_gain')

im,d=new(930)
text(d,(850,80),'预测标签',39,BLUE,'mm')
for j,t in enumerate(['合法','非法']):text(d,(800+j*470,150),t,36,INK,'mm')
for i,t in enumerate(['真实合法','真实非法']):text(d,(360,330+i*255),t,36,INK,'mm')
for i,row in enumerate([[53729,159],[1516,1032]]):
 for j,v in enumerate(row):
  x=570+j*470;y=215+i*255;c='#DCEBEA' if i==j else '#F7E8D7'
  d.rectangle((x,y,x+440,y+235),fill=c,outline='white',width=6);text(d,(x+220,y+115),f'{v:,}',55,INK,'mm')
text(d,(900,835),'已知测试地址56436；评估阈值约27.9512分',33,GRAY,'mm');save(im,'confusion')

im,d=new(950)
text(d,(100,65),'全图标签组成',43,BLUE)
vals=[251088,14266,557588];cols=[BLUE,GOLD,'#ADBACA'];start=100
for val,c in zip(vals,cols):
 w=1600*val/sum(vals);d.rectangle((start,160,start+w,290),fill=c);start+=w
for i,(s,c) in enumerate(zip(['已知合法 251,088','已知非法 14,266','未知 557,588'],cols)):
 x=100+i*555;d.rectangle((x,340,x+26,366),fill=c);text(d,(x+45,330),s,32)
text(d,(100,465),'已知标签的时间划分',43,BLUE)
for i,(s,v,c) in enumerate([('训练',170404,BLUE),('验证',38514,TEAL),('测试',56436,GOLD)]):
 x=100+i*555;box(d,x,560,510,210,s,f'{v:,} 个地址\n截止时段 {[34,41,49][i]}',c,kind='db')
text(d,(900,875),'unknown不进入监督损失，但可以参与无标签图结构与推理',32,GRAY,'mm');save(im,'dataset')

im,d=new(1120)
for k,(ti,desc) in enumerate([('低分连接','低分中间节点后存在目标'),('高连接噪声','大量分支中保留真实入口'),('循环与死端','拒绝回环与无目标分支'),('平行分支','有限名额中的覆盖选择')]):
 x=80+(k%2)*870;y=60+(k//2)*500
 box(d,x,y,780,440,ti,desc,BLUE if k%2==0 else TEAL,kind='graph')
 if k==0:
  pts=[(90,275),(270,275),(450,275),(640,275)];edges=[(0,1),(1,2),(2,3)];target=3
 elif k==1:
  pts=[(95,290),(270,210),(270,280),(270,350),(470,350),(645,350),(470,210)];edges=[(0,1),(0,2),(0,3),(3,4),(4,5),(1,6)];target=5
 elif k==2:
  pts=[(90,265),(280,265),(280,375),(470,265),(660,265),(470,375)];edges=[(0,1),(1,2),(2,0),(1,3),(3,4),(3,5)];target=4
 else:
  pts=[(80,300),(300,190),(300,260),(300,330),(300,400),(650,190),(650,260),(650,330),(650,400)];edges=[(0,j) for j in range(1,5)]+[(j,j+4) for j in range(1,5)];target=5
 for a,b in edges:
  aa=(x+pts[a][0],y+pts[a][1]);bb=(x+pts[b][0],y+pts[b][1]);dx=bb[0]-aa[0];dy=bb[1]-aa[1];ll=math.hypot(dx,dy)
  arrow(d,(aa[0]+dx/ll*20,aa[1]+dy/ll*20),(bb[0]-dx/ll*24,bb[1]-dy/ll*24),'#8195A9',4)
 for j,(xx,yy) in enumerate(pts):
  c=TEAL if j==target or (k==3 and j>=5) else ('#C6852F' if k==0 and j in [1,2] else '#B3C8DE')
  d.ellipse((x+xx-17,y+yy-17,x+xx+17,y+yy+17),fill=c)
text(d,(900,1080),'每类12个固定种子实例，共48个机制图；示意结构不代表AML真实路径标签',30,GRAY,'mm');save(im,'mechanisms')
print('figures',len(list(OUT.glob('*.png'))))
