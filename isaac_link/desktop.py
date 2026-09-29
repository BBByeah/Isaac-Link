"""Native Qt desktop. Rendering is bounded and independent of network polling."""
import argparse
import collections
import itertools
import math
from pathlib import Path
import sys
import threading
import time
from PySide6.QtCore import Qt, QTimer, Signal, QPointF, QRectF, QPoint, QRect
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QPainterPath
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QFrame,QSplitter,QPlainTextEdit,QCheckBox,QProgressBar,QScrollArea,QStackedWidget,QSizePolicy)
from isaac_link.expansion import Expansion
from isaac_link.inline_box import InlineBox
from isaac_link.desktop_backend import DesktopBackend
from isaac_link.backend import ROOT
from isaac_link.routing import LABELS, edge
from isaac_link.stun import DEFAULT_SERVERS
from isaac_link.version import __version__

THEMES={'green':('#9ac7ac','#121816','#1b2420','#26332c'),'wine':('#c34d4d','#180d0d','#291515','#491b1b'),
        'gold':('#dbbf80','#191710','#272319','#393321'),'purple':('#bea7e2','#17131e','#241e2d','#342a42')}
COLORS={'lan':'#79d1c0','ipv6':'#a2d0a9','ipv4':'#82b7e5','steam':'#baa2e0','relay':'#d4b778'}

def panel():
    frame=QFrame();frame.setObjectName('panel');return frame

def button(text,callback,primary=False):
    b=QPushButton(text);b.clicked.connect(callback)
    if primary:b.setObjectName('primary')
    return b

class Spark(QWidget):
    def __init__(self):
        super().__init__();self.points=collections.deque(maxlen=120);self.accent='#9ac7ac';self.setMinimumHeight(44)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);w=self.width();h=self.height()
        p.setPen(QPen(QColor('#35413b'),1))
        for y in (h*.25,h*.75):p.drawLine(QPointF(0,y),QPointF(w,y))
        if not self.points:return
        valid=[v for v in self.points if v is not None];scale=max(30,max(valid,default=30)*1.2)
        path=QPainterPath();started=False
        for i,value in enumerate(self.points):
            if value is None:started=False;continue
            point=QPointF(w*i/max(119,len(self.points)-1),h-4-(h-8)*value/scale)
            if started:path.lineTo(point)
            else:path.moveTo(point);started=True
        p.setPen(QPen(QColor(self.accent),2));p.drawPath(path)

class Topology(QWidget):
    selected=Signal(str,str)
    player_selected=Signal(str)
    def __init__(self):
        super().__init__();self.state={};self.hits=[];self.highlighted=None;self.accent='#9ac7ac';self.surface='#1b2420';self.control='#23342a';self.setMinimumSize(380,240)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);self.hits=[];self.label_hits=[];self.player_hits=[]
        members=self.state.get('room',{}).get('members',[]);edges=self.state.get('edges',{})
        center=QPointF(self.width()/2,self.height()/2)
        if not members:
            p.setPen(QColor('#81978a'));p.drawText(self.rect(),Qt.AlignCenter,'连接游戏，开始组队\n\n无需配置服务器');return
        x0=78;x1=self.width()-78;y0=65;y1=self.height()-65
        layouts={1:[center],2:[QPointF(x0,center.y()),QPointF(x1,center.y())],
                 3:[QPointF(center.x(),y0),QPointF(x1,y1),QPointF(x0,y1)],
                 4:[QPointF(x0,y0),QPointF(x1,y0),QPointF(x1,y1),QPointF(x0,y1)]}
        positions={m['steam']:pos for m,pos in zip(members,layouts[len(members)])};labels=[]
        pairs=list(enumerate(itertools.combinations(positions,2)))
        pairs.sort(key=lambda item:edge(*item[1])==self.highlighted)
        for index,(a,b) in pairs:
            rec=edges.get(edge(a,b),{});active=rec.get('active') and not rec.get('stale');route=rec.get('route')
            color=QColor(COLORS.get(route,'#526259') if active else '#435149')
            highlighted=edge(a,b)==self.highlighted
            if self.highlighted and not highlighted:color.setAlpha(65)
            if highlighted:
                glow=QColor(self.accent);glow.setAlpha(55);p.setPen(QPen(glow,11));p.drawLine(positions[a],positions[b])
            p.setPen(QPen(color,3.5 if highlighted else 2,Qt.SolidLine if active else Qt.DashLine));p.drawLine(positions[a],positions[b])
            fraction=.34 if index==1 and len(members)==4 else .66 if index==4 and len(members)==4 else .5
            mid=positions[a]*(1-fraction)+positions[b]*fraction
            # Paint every label after all lines, so later lines cannot cut through text.
            text=LABELS.get(route,'等待连通') if active else '数据已过期' if rec.get('stale') else '等待恢复'
            p.setFont(QFont('Microsoft YaHei UI',9));width=max(94,p.fontMetrics().horizontalAdvance(text)+24)
            labels.append((QRectF(mid.x()-width/2,mid.y()-16,width,32),text,color,a,b))
            self.hits.append((positions[a],positions[b],a,b))
        self.label_hits=[]
        for rect,text,color,a,b in labels:
            p.setBrush(QColor(self.surface));p.setPen(QPen(color,2.5 if edge(a,b)==self.highlighted else 1));p.drawRoundedRect(rect,8,8)
            p.setPen(color);p.drawText(rect,Qt.AlignCenter,text);self.label_hits.append((rect,a,b))
        for m in members:
            point=positions[m['steam']];rect=QRectF(point.x()-60,point.y()-35,120,70)
            self.player_hits.append((rect,m['steam']))
            highlighted=bool(self.highlighted and m['steam'] in self.highlighted.split(':'))
            p.setOpacity(.4 if self.highlighted and not highlighted else 1)
            p.setBrush(QColor(self.control));p.setPen(QPen(QColor(self.accent),3 if highlighted else 1.5));p.drawRoundedRect(rect,12,12)
            p.setPen(QColor('#e4eee7'));p.setFont(QFont('Segoe UI',11,QFont.Bold));p.drawText(QRectF(rect.x()+6,rect.y()+10,108,24),Qt.AlignCenter,m['player_id'])
            p.setFont(QFont('Microsoft YaHei UI',9));p.setPen(QColor(self.accent));p.drawText(QRectF(rect.x()+6,rect.y()+38,108,20),Qt.AlignCenter,'房主' if m['steam']==self.state['room']['host'] else '成员')
    def mousePressEvent(self,event):
        q=event.position()
        for rect,steam in getattr(self,'player_hits',[]):
            if rect.contains(q):self.player_selected.emit(steam);return
        for rect,left,right in getattr(self,'label_hits',[]):
            if rect.contains(q):self.selected.emit(left,right);return
        for a,b,left,right in self.hits:
            dx=b.x()-a.x();dy=b.y()-a.y();length=dx*dx+dy*dy
            t=max(0,min(1,((q.x()-a.x())*dx+(q.y()-a.y())*dy)/length)) if length else 0
            if math.hypot(q.x()-a.x()-t*dx,q.y()-a.y()-t*dy)<16:self.selected.emit(left,right);return

class EdgeCard(QFrame):
    clicked=Signal()
    hovered=Signal(bool)
    def __init__(self):
        super().__init__();self.setObjectName('card');self.setCursor(Qt.PointingHandCursor);layout=QVBoxLayout(self);layout.setContentsMargins(10,8,10,8);layout.setSpacing(4)
        row=QHBoxLayout();self.title=QLabel();self.title.setObjectName('muted');row.addWidget(self.title,1)
        self.metric_label=QLabel('—');self.metric_label.setObjectName('metric');row.addWidget(self.metric_label);layout.addLayout(row)
        self.spark=Spark();self.spark.setMinimumHeight(72);self.spark.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding);layout.addWidget(self.spark,1)
        row=QHBoxLayout();self.route=QLabel();self.route.setObjectName('cardMeta');row.addWidget(self.route,1)
        self.foot=QLabel();self.foot.setObjectName('cardMeta');row.addWidget(self.foot);layout.addLayout(row)
    def mousePressEvent(self,event):self.clicked.emit()
    def set_highlighted(self,value):
        if bool(self.property('highlighted'))==value:return
        self.setProperty('highlighted',value);self.style().unpolish(self);self.style().polish(self);self.update()
    def enterEvent(self,event):self.set_highlighted(True);self.hovered.emit(True);super().enterEvent(event)
    def leaveEvent(self,event):self.set_highlighted(False);self.hovered.emit(False);super().leaveEvent(event)
    def hideEvent(self,event):self.set_highlighted(False);self.hovered.emit(False);super().hideEvent(event)

class Window(QMainWindow):
    finished=Signal()
    def __init__(self,backend=None,demo=False):
        super().__init__();self.backend=backend or DesktopBackend();self.demo=demo;self.state={};self.cards={};self.last_plot=0;self.exiting=False;self.allow_close=False;self.expansion=None;self.inline=None;self.sim_lan={}
        self.setWindowTitle('Isaac-Link · 以撒联机助手');self.resize(1320,860);self.setMinimumSize(980,680)
        self.simulated=demo;self.sim_count=4;self.sim_scenario='normal';self.sim_modes={};self.sim_control='steam';self.stun_result=None
        self.pages=QStackedWidget();self.setCentralWidget(self.pages)
        root=QWidget();self.pages.addWidget(root);layout=QVBoxLayout(root);layout.setContentsMargins(24,20,24,16);layout.setSpacing(16)
        header=QHBoxLayout();brand=QLabel('ISAAC-LINK');brand.setObjectName('brand');header.addWidget(brand)
        badge=QLabel(__version__);badge.setObjectName('muted');header.addWidget(badge);header.addStretch()
        self.theme=QComboBox()
        for key,label in (('green','墨绿'),('wine','酒红'),('gold','黑金'),('purple','紫色')):self.theme.addItem(label,key)
        self.theme.setCurrentIndex(max(0,self.theme.findData(self.backend.profile.get('theme','green'))));self.theme.currentIndexChanged.connect(self.change_theme)
        self.status=QLabel('尚未连接游戏');self.status.setObjectName('status');header.addWidget(self.status)
        header.addWidget(button('设置',self.settings_dialog));header.addWidget(button('检查更新',self.update_dialog));layout.addLayout(header)
        connect=panel();cl=QVBoxLayout(connect);cl.setContentsMargins(18,16,18,16);cl.setSpacing(12)
        row=QHBoxLayout();self.name=QLineEdit(self.backend.profile.get('player_id',''));self.name.setPlaceholderText('五字母玩家 ID');self.name.setMaximumWidth(160);self.name.setMaxLength(5)
        self.server=QLineEdit(self.backend.saved_server_code);self.server.setPlaceholderText('可选：服务器连接码。不填写也能组队');self.server.setEchoMode(QLineEdit.Password)
        self.connect_btn=button('连接游戏',self.connect_game,True);self.disconnect_btn=button('断开',lambda:self.command('disconnect'))
        row.addWidget(self.name);row.addWidget(self.server,1);row.addWidget(self.connect_btn);row.addWidget(self.disconnect_btn);cl.addLayout(row)
        row=QHBoxLayout();self.code=QLineEdit();self.code.setReadOnly(True);self.code.setPlaceholderText('连接后生成个人连接码')
        row.addWidget(self.code,1);row.addWidget(button('复制',lambda:QApplication.clipboard().setText(self.code.text())))
        self.join=QLineEdit();self.join.setPlaceholderText('房主粘贴队友连接码');row.addWidget(self.join,1)
        self.add_btn=button('邀请队友',lambda:self.command('add',code=self.join.text().strip()));row.addWidget(self.add_btn);cl.addLayout(row);layout.addWidget(connect)
        self.notice=QLabel('请先从 Steam 启动忏悔＋，停留在主菜单。');self.notice.setObjectName('muted');self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.invitation=QPushButton();self.invitation.hide();self.invitation.clicked.connect(self.accept_invite);layout.addWidget(self.invitation)
        split=QSplitter();split.setChildrenCollapsible(False)
        left=panel();ll=QVBoxLayout(left);ll.setContentsMargins(18,16,18,12)
        heading=QHBoxLayout();heading.addWidget(QLabel('队伍连接'));heading.addStretch();self.auto=button('全队自动',lambda:self.command('test'));heading.addWidget(self.auto);ll.addLayout(heading)
        self.graph=Topology();self.graph.selected.connect(self.edge_dialog);self.graph.player_selected.connect(self.player_details);ll.addWidget(self.graph,1)
        self.member_label=QLabel('支持 2–4 人  ·  点击连线查看详情');self.member_label.setObjectName('muted');ll.addWidget(self.member_label)
        lr=QHBoxLayout();lr.addStretch();lr.addWidget(button('解散房间',self.dissolve));ll.addLayout(lr)
        split.addWidget(left)
        right=panel();rl=QVBoxLayout(right);rl.setContentsMargins(16,16,16,12)
        top=QHBoxLayout();top.addWidget(QLabel('连接质量'));top.addStretch();self.monitor=QCheckBox('监测');self.monitor.setChecked(True);self.monitor.clicked.connect(lambda v:self.command('settings',monitor=v));top.addWidget(self.monitor);rl.addLayout(top)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);container=QWidget();self.grid=QGridLayout(container);self.grid.setContentsMargins(0,0,0,0);self.grid.setSpacing(10);scroll.setWidget(container);rl.addWidget(scroll,1)
        self.empty=QLabel('等待队友加入\n\n每对玩家独立选路，每 30 秒评估一次。');self.empty.setAlignment(Qt.AlignCenter);self.grid.addWidget(self.empty,0,0)
        self.monitor_note=QLabel('RTT 为往返延迟；曲线保留最近 120 秒。');self.monitor_note.setObjectName('muted');rl.addWidget(self.monitor_note)
        split.addWidget(right);split.setSizes([590,650]);layout.addWidget(split,1)
        footer=QHBoxLayout();self.bottom=QLabel('协调通道与游戏线路独立运行');self.bottom.setObjectName('muted');footer.addWidget(self.bottom,1)
        footer.addWidget(button('日志',self.logs_dialog));layout.addLayout(footer)
        self.build_settings()
        self.finished.connect(self.finish_close)
        self.apply_theme();self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(250)
        if not demo:
            threading.Thread(target=self.backend.discover,daemon=True).start()
            if self.backend.profile.get('check_updates',True):QTimer.singleShot(2000,lambda:self.command('update-check'))
        self.refresh()

    def command(self,action,**data):
        if self.simulated:
            if action=='test':
                for modes in self.sim_modes.values():modes['game_mode']='auto'
            return
        if not self.demo:self.backend.submit({'action':action,**data})

    def apply_theme(self):
        accent,bg,surface,control=THEMES[self.theme.currentData()]
        self.graph.accent=accent;self.graph.surface=surface;self.graph.control=control;self.graph.update()
        for card in self.cards.values():card.spark.accent=accent;card.spark.update()
        self.setStyleSheet(f'''
        QWidget{{font-family:"Microsoft YaHei UI";font-size:12px;color:#e7ece8;}}
        QMainWindow,QStackedWidget,QPlainTextEdit>QWidget{{background:{bg};}} QFrame#panel{{background:{surface};border:1px solid {control};border-radius:14px;}}
        QFrame#expansion{{background:{surface};border:1px solid {accent};border-radius:14px;}}
        QFrame#inlineDetail{{background:{surface};border:1px solid {accent};border-radius:9px;}}
        QPushButton#inlineRoute{{text-align:left;padding:5px 9px;min-height:18px;}}
        QPushButton#inlineRoute:checked{{border-color:{accent};color:{accent};}}
        QFrame#card{{background:{bg};border:1px solid {control};border-radius:10px;}}
        QFrame#card[highlighted="true"]{{background:{control};border-color:{accent};}}
        QLabel#brand{{font-size:20px;font-weight:700;letter-spacing:2px;color:{accent};}} QLabel#hero{{font-size:25px;font-weight:600;}}
        QLabel#muted{{color:#99aaa0;font-size:11px;}} QLabel#status{{color:{accent};}} QLabel#metric{{font-size:16px;font-weight:600;}}
        QLabel#cardMeta{{color:#99aaa0;font-size:10px;}}
        QPushButton,QComboBox{{background:{control};border:1px solid {control};border-radius:7px;padding:8px 13px;}}
        QPushButton:hover{{border-color:{accent};}} QPushButton:disabled{{color:#627168;}} QPushButton#primary{{background:{accent};color:{bg};font-weight:700;}}
        QLineEdit,QPlainTextEdit{{background:{bg};border:1px solid {control};border-radius:7px;padding:9px;selection-background-color:{accent};}}
        QLineEdit:focus{{border-color:{accent};}} QComboBox QAbstractItemView{{background:{surface};selection-background-color:{control};}}
        QComboBox{{padding-right:32px;min-height:20px;}} QComboBox::drop-down{{subcontrol-origin:padding;subcontrol-position:top right;width:28px;border:0;}}
        QComboBox::down-arrow{{image:url({(Path(__file__).parent/'chevron.svg').as_posix()});width:12px;height:12px;}}
        QScrollArea,QScrollArea>QWidget>QWidget{{background:transparent;}} QScrollBar:vertical{{background:{bg};width:8px;}} QScrollBar::handle:vertical{{background:{control};border-radius:4px;}}
        QSplitter::handle{{background:transparent;width:16px;}} QToolTip{{background:{surface};color:#eeeeee;border:1px solid {accent};}}
        QProgressBar{{background:{bg};border:1px solid {control};border-radius:6px;text-align:center;height:20px;}} QProgressBar::chunk{{background:{accent};}}
        ''')

    def change_theme(self):
        self.apply_theme()
        if not self.demo:self.backend.submit({'action':'theme','theme':self.theme.currentData()})
    def connect_game(self):self.command('connect',player_id=self.name.text().strip(),server_code=self.server.text().strip())

    def refresh(self):
        self.state=demo_state(self.sim_count,self.sim_scenario,self.sim_modes) if self.simulated else self.backend.state();s=self.state
        if self.simulated:
            for member in s.get('room',{}).get('members',[]):member['lan_ip']=self.sim_lan.get(member['steam'],'')
            s['room']['control_route']=self.sim_control
            for rec in s.get('edges',{}).values():rec['control']=self.sim_control;rec['control_mode']=self.sim_control
        self.team_control.blockSignals(True);self.team_control.setCurrentIndex(self.team_control.findData(s.get('room',{}).get('control_route','steam')));self.team_control.blockSignals(False)
        self.team_control.setEnabled(s.get('is_host',False))
        if self.stun_result is not None:
            self.stun_status.setText(self.stun_result);self.stun_result=None;self.stun_test.setEnabled(True)
        if self.isMinimized():return
        self.graph.state=s;self.graph.update()
        self.code.setText(s.get('code',''));connected=s.get('connected',False);host=s.get('is_host',False)
        steam=s.get('steam',{}).get('peers',{});steam_active=sum(bool(v.get('active')) for v in steam.values())
        self.status.setText('接口已断开 · 请重新连接游戏' if s.get('failure') else '已接管 · Steam '+str(steam_active)+' 条在线' if s.get('enabled') else '已连接游戏 · 等待队友' if connected else '尚未连接游戏')
        if self.simulated:self.status.setText('开发者模拟 · '+str(self.sim_count)+' 名成员')
        self.connect_btn.setEnabled(not self.simulated and not s.get('busy'));self.disconnect_btn.setEnabled(connected and not self.simulated);self.add_btn.setEnabled(host and not self.simulated);self.auto.setEnabled(host);self.monitor.setEnabled(host)
        self.monitor.setChecked(s.get('room',{}).get('monitor',True));self.capture.setEnabled(connected and not self.simulated)
        self.capture.setText('停止抓包' if s.get('capture',{}).get('active') else '开始抓包')
        offers=s.get('room',{}).get('offers',[]);self.invitation.setVisible(bool(offers))
        if offers:self.invitation.setText('收到 '+offers[0]['player_id']+' 的组队邀请 · 点击接受')
        update=s.get('update',{});manifest=update.get('manifest') or {}
        hint=s.get('failure') or s.get('error') or s.get('busy') or s.get('room',{}).get('error')
        pending=s.get('room',{}).get('sync_pending',[])
        if not hint and pending:hint='配置等待同步：'+ '、'.join(pending)+'。协调线路不可用时会等待恢复。'
        if not hint and update.get('status')=='available' and manifest.get('version')!=s.get('profile',{}).get('ignored_version'):hint='发现新版 '+manifest['version']+'，可在“检查更新”中查看并选择升级。'
        self.notice.setText(hint or ('默认自动选路；手动固定后断线只重试该线路。' if connected else '请先从 Steam 启动忏悔＋，停留在主菜单。'))
        if self.simulated:self.notice.setText('开发者模拟已开启 · '+str(self.sim_count)+' 名成员 · 数据不来自真实连接；在设置中关闭。')
        self.bottom.setText('协调服务器：'+s.get('server','未配置')+'  ·  '+str(len(s.get('room',{}).get('members',[])))+' / 4 人')
        members={m['steam']:m['player_id'] for m in s.get('room',{}).get('members',[])}
        edges=s.get('edges',{});self.empty.setVisible(not edges)
        if self.graph.highlighted not in edges:self.graph.highlighted=None
        for key in list(self.cards):
            if key not in edges:self.cards.pop(key).deleteLater()
        append=time.monotonic()-self.last_plot>=1
        if append:self.last_plot=time.monotonic()
        for i,(key,rec) in enumerate(edges.items()):
            if key not in self.cards:
                card=EdgeCard();a,b=key.split(':');card.clicked.connect(lambda a=a,b=b:self.edge_dialog(a,b));card.hovered.connect(lambda value,key=key:self.highlight_pair(key,value));self.cards[key]=card
                if self.simulated:card.spark.points.extend(rec['rtt']+math.sin(j*.3+i)*4 for j in range(60))
            card=self.cards[key];card.spark.accent=THEMES[self.theme.currentData()][0];self.grid.addWidget(card,i//2,i%2)
            card.title.setText(members.get(rec['a'],rec['a'])+'  ↔  '+members.get(rec['b'],rec['b']))
            rtt=rec.get('rtt');stale=rec.get('stale');active=rec.get('active') and not stale
            card.metric_label.setText(f'{rtt:.0f} ms' if rtt is not None and active else '—')
            card.route.setText(LABELS.get(rec.get('route'),'等待连通')+' · '+('自动' if rec.get('game_mode')=='auto' else '固定'))
            text='监测数据已过期' if stale else '固定线路不可用' if not active and rec.get('game_mode')!='auto' else '正在恢复' if not active else '协调：'+LABELS.get(rec.get('control'),'不可用')
            card.foot.setText(text if not active else '');card.foot.setVisible(not active)
            if append and self.monitor.isChecked():card.spark.points.append(rtt if active else None);card.spark.update()

    def highlight_pair(self,key,enabled):
        if enabled:self.graph.highlighted=key
        elif self.graph.highlighted==key:self.graph.highlighted=None
        self.graph.update()

    def open_inline(self,rect,width,height):
        self.clear_details();parent=self.graph.parentWidget()
        origin=QRect(self.graph.mapTo(parent,rect.topLeft().toPoint()),rect.size().toSize())
        box=InlineBox(parent,origin,width,height);self.inline=box
        def dismissed():
            if self.inline is box:self.inline=None
        box.dismissed.connect(dismissed);return box

    def edge_dialog(self,a,b):
        rect=next((r for r,x,y in self.graph.label_hits if edge(x,y)==edge(a,b)),QRectF(100,100,94,32))
        box=self.open_inline(rect,260,255);layout=box.content;rec=self.state.get('edges',{}).get(edge(a,b),{})
        title=QLabel(LABELS.get(rec.get('route'),'等待连通'));title.setAlignment(Qt.AlignCenter);title.setFixedHeight(24);layout.addWidget(title)
        choices={}
        for route in ('auto','lan','ipv6','ipv4','steam','relay'):
            choice=button('',lambda checked=False,route=route:self.choose_route(a,b,'game',route));choice.setObjectName('inlineRoute');choice.setCheckable(True);layout.addWidget(choice);choices[route]=choice
        def refresh_routes():
            current=self.state.get('edges',{}).get(edge(a,b),{});field='game_mode'
            title.setText(LABELS.get(current.get('route'),'等待连通'))
            for route,choice in choices.items():
                metric=current.get('links',{}).get(route,{})
                latency=metric.get('p95') if not current.get('stale') and route in current.get('available',[]) else None
                label='自动' if route=='auto' else LABELS[route]+'    '+(f'{latency:.0f} ms' if latency is not None else '—')
                choice.setText(label);choice.setChecked(current.get(field,'auto')==route);choice.setEnabled(self.state.get('is_host',False))
        timer=QTimer(box);timer.timeout.connect(refresh_routes);timer.start(250);refresh_routes();box.open()

    def choose_route(self,a,b,plane,route):
        if not self.state.get('is_host'):return
        if self.simulated:
            self.sim_modes.setdefault(edge(a,b),{})[plane+'_mode']=route;self.refresh();return
        rt=self.backend.runtime
        if rt:
            def apply():
                try:rt.set_route(a,b,route,plane)
                except Exception as e:self.backend.error=str(e)
            threading.Thread(target=apply,daemon=True).start()

    def player_details(self,steam):
        member=next((m for m in self.state.get('room',{}).get('members',[]) if m['steam']==steam),None)
        if not member:return
        rect=next((r for r,s in self.graph.player_hits if s==steam),QRectF(100,100,120,70))
        box=self.open_inline(rect,270,165);layout=box.content;title=QLabel(member['player_id']);title.setAlignment(Qt.AlignCenter);layout.addWidget(title)
        ip=QLineEdit(member.get('lan_ip',''));ip.setPlaceholderText('局域网 IPv4');ip.setEnabled(self.state.get('is_host',False));layout.addWidget(ip)
        def save():
            import ipaddress
            value=ip.text().strip()
            try:
                if value:ipaddress.IPv4Address(value)
            except ValueError:ip.setPlaceholderText('IPv4 地址格式错误');ip.clear();return
            if self.simulated:self.sim_lan[steam]=value;self.refresh()
            else:self.command('lan',steam=steam,ip=value)
            box.collapse()
        row=QHBoxLayout();save_btn=button('保存',save);save_btn.setEnabled(self.state.get('is_host',False));row.addWidget(save_btn)
        if steam!=self.state.get('room',{}).get('self'):
            kick=button('移出',lambda:(self.command('kick',steam=steam),box.collapse()));kick.setEnabled(self.state.get('is_host',False));row.addWidget(kick)
        layout.addLayout(row);box.open()

    def accept_invite(self):
        offers=self.state.get('room',{}).get('offers',[])
        if offers:self.command('accept',steam=offers[0]['steam'])

    def settings_dialog(self):
        self.clear_details()
        self.redundancy.setChecked(self.state.get('room',{}).get('redundancy','window4')=='window4')
        self.redundancy.setEnabled(self.state.get('is_host',False));self.pages.setCurrentIndex(1)

    def change_team_control(self):
        route=self.team_control.currentData()
        if self.simulated:self.sim_control=route;self.refresh()
        else:self.command('control-route',route=route)

    def build_settings(self):
        page=QWidget();outer=QVBoxLayout(page);outer.setContentsMargins(24,20,24,20);outer.setSpacing(16)
        header=QHBoxLayout();header.addWidget(button('← 返回联机',lambda:self.pages.setCurrentIndex(0)));title=QLabel('设置');title.setObjectName('hero');header.addWidget(title);header.addStretch();outer.addLayout(header)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);body=QWidget();layout=QVBoxLayout(body);layout.setSpacing(16);layout.setContentsMargins(0,0,8,0);scroll.setWidget(body);outer.addWidget(scroll)
        general=panel();g=QVBoxLayout(general);g.setContentsMargins(20,18,20,18);g.setSpacing(14);g.addWidget(QLabel('外观与联机'))
        row=QHBoxLayout();row.addWidget(QLabel('主题颜色'));self.theme.setMinimumWidth(180);row.addWidget(self.theme);row.addStretch();g.addLayout(row)
        auto=QCheckBox('启动时检查更新');auto.setChecked(self.backend.profile.get('check_updates',True));auto.clicked.connect(lambda v:self.backend.submit({'action':'auto-update','enabled':v}));g.addWidget(auto)
        self.redundancy=QCheckBox('四帧输入冗余');self.redundancy.clicked.connect(lambda v:self.command('settings',redundancy='window4' if v else 'off'));g.addWidget(self.redundancy)
        row=QHBoxLayout();row.addWidget(QLabel('全队协调线路'));self.team_control=QComboBox()
        for route in ('steam','relay','lan','ipv6','ipv4'):self.team_control.addItem(LABELS[route],route)
        self.team_control.activated.connect(self.change_team_control);row.addWidget(self.team_control);row.addStretch();g.addLayout(row);layout.addWidget(general)
        network=panel();n=QVBoxLayout(network);n.setContentsMargins(20,18,20,18);n.setSpacing(12);n.addWidget(QLabel('网络 · STUN 节点'))
        note=QLabel('用于发现 IPv4 公网地址。能否访问取决于当前运营商和网络，请先检测。节点不可达时仍可使用 Steam 线路。');note.setWordWrap(True);note.setObjectName('muted');n.addWidget(note)
        self.stun=QPlainTextEdit(self.backend.profile.get('stun_servers','\n'.join(f'{h}:{p}' for h,p in DEFAULT_SERVERS)));self.stun.setFixedHeight(92);n.addWidget(self.stun)
        row=QHBoxLayout();row.addWidget(button('保存节点',self.save_stun));self.stun_test=button('检测可用性',self.check_stun);row.addWidget(self.stun_test);row.addStretch();n.addLayout(row)
        self.stun_status=QLabel('每行填写 域名:端口；保存后下次连接生效。');self.stun_status.setWordWrap(True);self.stun_status.setObjectName('muted');n.addWidget(self.stun_status);layout.addWidget(network)
        developer=panel();d=QVBoxLayout(developer);d.setContentsMargins(20,18,20,18);d.setSpacing(12);d.addWidget(QLabel('开发者测试'))
        self.sim_toggle=QCheckBox('模拟成员与连接数据');self.sim_toggle.setChecked(self.simulated);self.sim_toggle.clicked.connect(self.toggle_simulation);d.addWidget(self.sim_toggle)
        note=QLabel('无需启动游戏。模拟期间不发送网络或游戏指令；关闭后恢复实际状态。');note.setObjectName('muted');note.setWordWrap(True);d.addWidget(note)
        row=QHBoxLayout();row.addWidget(QLabel('成员数量（含自己）'));count=QComboBox()
        for value in range(1,5):count.addItem(str(value)+' 人',value)
        count.setCurrentIndex(self.sim_count-1);count.currentIndexChanged.connect(lambda:self.set_sim_count(count.currentData()));row.addWidget(count)
        row.addWidget(QLabel('连接状态'));scenario=QComboBox()
        for label,key in [('正常连接','normal'),('高延迟 / 丢包','loss'),('线路断开','offline'),('监测过期','stale')]:scenario.addItem(label,key)
        scenario.currentIndexChanged.connect(lambda:self.set_sim_scenario(scenario.currentData()));row.addWidget(scenario);row.addStretch();d.addLayout(row)
        row=QHBoxLayout();row.addWidget(button('查看模拟拓扑',lambda:self.pages.setCurrentIndex(0)));self.capture=button('开始抓包',lambda:self.command('capture'));row.addWidget(self.capture);row.addStretch();d.addLayout(row)
        hint=QLabel('抓包仅对真实连接生效。');hint.setObjectName('muted');d.addWidget(hint);layout.addWidget(developer);layout.addStretch();self.pages.addWidget(page)

    def toggle_simulation(self,enabled):
        if enabled and self.backend.runtime:
            self.sim_toggle.setChecked(False);self.show_message('模拟成员','请先断开游戏连接，再开启模拟。');return
        self.simulated=enabled;self.sim_modes.clear()
        for card in self.cards.values():card.spark.points.clear()
        self.refresh()

    def set_sim_count(self,count):self.sim_count=count;self.refresh()
    def set_sim_scenario(self,scenario):self.sim_scenario=scenario;self.refresh()

    def save_stun(self):
        from isaac_link.stun import parse_servers
        try:parse_servers(self.stun.toPlainText())
        except ValueError as e:self.stun_status.setText(str(e));return
        self.backend.submit({'action':'stun-settings','text':self.stun.toPlainText()});self.stun_status.setText('已提交保存；下次连接生效。')

    def check_stun(self):
        from isaac_link.stun import parse_servers,check_servers
        try:servers=parse_servers(self.stun.toPlainText())
        except ValueError as e:self.stun_status.setText(str(e));return
        self.stun_test.setEnabled(False);self.stun_status.setText('正在检测当前网络…')
        def run():
            try:self.stun_result='\n'.join(f'{host}:{port} · {status}' for host,port,status in check_servers(servers))
            except Exception as e:self.stun_result='检测未完成：'+str(e)
        threading.Thread(target=run,daemon=True).start()

    def logs_dialog(self):
        d=self.open_details('运行日志',width=820,height=520);text=QPlainTextEdit();text.setReadOnly(True);text.setMinimumHeight(300);text.setPlainText('\n'.join(self.state.get('logs',[])));d.content.addWidget(text)
        timer=QTimer(d)
        def refresh_logs():
            latest='\n'.join(self.state.get('logs',[]))
            if text.toPlainText()!=latest:text.setPlainText(latest)
        timer.timeout.connect(refresh_logs);timer.start(1000);d.open()

    def update_dialog(self):
        dialog=self.open_details('版本更新',width=620,height=500);layout=dialog.content
        status=QLabel();status.setWordWrap(True);layout.addWidget(status);notes=QPlainTextEdit();notes.setReadOnly(True);layout.addWidget(notes);progress=QProgressBar();layout.addWidget(progress)
        row=QHBoxLayout();check=button('检查',lambda:self.command('update-check'));download=button('下载新版',lambda:self.command('update-download'));install=button('安装并重启',self.install_update)
        for b in (check,download,install):row.addWidget(b)
        layout.addLayout(row);row=QHBoxLayout();ignore=button('忽略本版本',lambda:self.command('update-ignore'));row.addWidget(ignore);row.addWidget(button('取消下载',lambda:self.command('update-cancel')));row.addWidget(button('稍后',dialog.collapse));layout.addLayout(row)
        def refresh():
            u=self.backend.updates;m=u.manifest or {};labels={'idle':'尚未检查','checking':'正在检查…','available':'发现新版 '+m.get('version',''),'latest':'已是最新稳定版','downloading':'正在下载…','ready':'已验证，等待安装','cancelled':'下载已取消','error':'检查或下载未完成'}
            status.setText(labels.get(u.status,u.status)+('\n'+u.error if u.error else ''));notes.setPlainText(m.get('notes','升级完全自愿，可继续使用当前版本。'));progress.setValue(u.progress)
            download.setEnabled(u.status in ('available','cancelled','error') and bool(m));install.setEnabled(u.status=='ready' and not self.backend.runtime);ignore.setEnabled(bool(m))
            install.setToolTip('请先断开游戏连接' if self.backend.runtime else '')
        timer=QTimer(dialog);timer.timeout.connect(refresh);timer.start(250);refresh()
        if self.backend.updates.status=='idle':self.command('update-check')
        dialog.open()

    def install_update(self):
        if self.backend.runtime:self.show_message('更新','请先结束联机并断开助手。');return
        try:self.backend.updates.launch_installer(ROOT)
        except Exception as e:self.show_message('更新未开始',str(e));return
        QApplication.closeAllWindows()

    def dissolve(self):
        if not self.state.get('is_host'):return
        detail=self.open_details('解散房间',height=230);detail.content.addWidget(QLabel('通知所有成员结束当前助手房间？'))
        def confirm():self.command('dissolve');detail.collapse()
        detail.content.addWidget(button('确认解散',confirm));detail.open()

    def open_details(self,title,anchor=None,width=580,height=500):
        source=anchor or self.sender()
        if not isinstance(source,QWidget):source=self.graph
        self.clear_details();detail=Expansion(self.pages,source,title,width,height);self.expansion=detail
        def dismissed():
            if self.expansion is detail:self.expansion=None
        detail.dismissed.connect(dismissed);return detail

    def clear_details(self):
        if self.inline:
            self.inline.animation.stop();self.inline.hide();self.inline.deleteLater();self.inline=None
        if self.expansion:
            self.expansion.animation.stop();self.expansion.hide();self.expansion.deleteLater();self.expansion=None

    def show_message(self,title,message):
        detail=self.open_details(title,height=250);text=QLabel(message);text.setWordWrap(True);detail.content.addWidget(text);detail.content.addStretch();detail.open()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.inline:self.clear_details()
        if self.expansion:self.expansion.relayout()

    def closeEvent(self,event):
        if self.allow_close:event.accept();return
        event.ignore()
        if self.exiting:return
        self.exiting=True;self.notice.setText('正在解除游戏接管并退出…');self.backend.close_async(self.finished.emit)
    def finish_close(self):self.allow_close=True;self.timer.stop();self.close()

def demo_state(count=4,scenario='normal',modes=None):
    members=[dict(steam=str(i+1),player_id=n) for i,n in enumerate(('WHEAT','ISAAC','MAGGY','AZAZL')[:count])];edges={}
    for i,(a,b) in enumerate(itertools.combinations(members,2)):
        route=('lan','ipv6','ipv4','steam','ipv6','ipv4')[i]
        rec=dict(a=a['steam'],b=b['steam'],route=route,control='ipv6',active=scenario!='offline',stale=scenario=='stale',rtt=18+i*7+math.sin(time.monotonic()+i)*4+(120 if scenario=='loss' else 0),
            game_mode='auto',control_mode='auto',available=['lan','steam','ipv6','ipv4'])
        rec.update((modes or {}).get(edge(a['steam'],b['steam']),{}))
        if rec['game_mode']!='auto':rec['route']=rec['game_mode']
        if rec['control_mode']!='auto':rec['control']=rec['control_mode']
        rec['links']={r:dict(p95=rec['rtt']+j*5,loss=.15 if scenario=='loss' else 0) for j,r in enumerate(rec['available'])}
        edges[edge(a['steam'],b['steam'])]=rec
    return dict(room=dict(members=members,host='1',self='1',monitor=True,redundancy='window4',offers=[]),edges=edges,is_host=True,connected=True,enabled=True,
                code='模拟连接码',server='未配置',profile={},update={})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--demo',action='store_true');parser.add_argument('--screenshot');parser.add_argument('--update-ready');args=parser.parse_args()
    app=QApplication(sys.argv[:1]);app.setApplicationName('Isaac-Link');window=Window(demo=args.demo);window.show()
    if args.update_ready:QTimer.singleShot(1000,lambda:Path(args.update_ready).write_text('ready',encoding='ascii'))
    if args.screenshot:
        Path(args.screenshot).parent.mkdir(parents=True,exist_ok=True)
        def capture():window.grab().save(args.screenshot);window.close()
        QTimer.singleShot(1200,capture)
    return app.exec()

if __name__=='__main__':sys.exit(main())
