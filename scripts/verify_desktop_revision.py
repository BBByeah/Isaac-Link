"""UI interaction and layout checks without a live game or network requests."""
import os
from pathlib import Path
import sys
import tempfile
import time

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QLineEdit
from PySide6.QtCore import Qt,QPoint,QPointF,QAbstractAnimation,QEvent
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase,QEnterEvent
from isaac_link.desktop import Window,THEMES
from isaac_link.desktop_backend import DesktopBackend

app=QApplication([])
def settled(detail):
    deadline=time.monotonic()+3
    while detail.animation.state()==QAbstractAnimation.Running and time.monotonic()<deadline:QTest.qWait(25)
for name in ('msyh.ttc','msyhbd.ttc','segoeui.ttf','segoeuib.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR'])/'Fonts'/name))
out=ROOT/'ui-validation';out.mkdir(exist_ok=True)
scale=os.environ.get('QT_SCALE_FACTOR','1')
hovered_card=None
def hover(widget,card=None):
    global hovered_card
    if scale=='1':QTest.mouseMove(widget,widget.rect().center())
    else:
        # A 2640 px offscreen window can exceed the physical cursor bounds.
        # Deliver Qt's logical enter/leave events without warping the OS cursor.
        if hovered_card:app.sendEvent(hovered_card,QEvent(QEvent.Leave))
        if card:
            point=card.rect().center();app.sendEvent(card,QEnterEvent(QPointF(point),QPointF(card.mapTo(card.window(),point)),QPointF(card.mapToGlobal(point))))
        hovered_card=card
    QTest.qWait(100)
with tempfile.TemporaryDirectory() as temp:
    backend=DesktopBackend(Path(temp));sent=[];backend.submit=lambda data:sent.append(data)
    w=Window(backend,demo=True);w.show();app.processEvents()
    w.settings_dialog();app.processEvents()
    assert w.pages.currentIndex()==1
    w.team_control.setCurrentIndex(w.team_control.findData('lan'));w.change_team_control()
    assert all(rec['control_mode']=='lan' for rec in w.state['edges'].values())
    w.team_control.setCurrentIndex(w.team_control.findData('steam'));w.change_team_control()
    assert not any(isinstance(x,QDialog) and x.isVisible() for x in app.topLevelWidgets())
    assert w.theme.isVisible() and w.capture.isVisible()
    for theme in THEMES:
        w.theme.setCurrentIndex(w.theme.findData(theme));app.processEvents()
        w.grab().save(str(out/f'revised-settings-{theme}-{scale}.png'))
        w.pages.setCurrentIndex(0);w.refresh();app.processEvents()
        assert not w.theme.isVisible() and not w.capture.isVisible()
        assert len(w.graph.label_hits)==6
        boxes=[r for r,_,_ in w.graph.label_hits]
        assert not any(a.intersects(b) for i,a in enumerate(boxes) for b in boxes[i+1:])
        w.grab().save(str(out/f'revised-desktop-{theme}-{scale}.png'))
        w.settings_dialog()
    w.pages.setCurrentIndex(0);w.refresh();app.processEvents()
    card=w.cards['1:2'];assert card.spark.height()>card.height()*.5,(card.spark.height(),card.height())
    hover(card.spark,card)
    assert card.property('highlighted') and w.graph.highlighted=='1:2'
    w.grab().save(str(out/f'card-hover-{scale}.png'))
    other=w.cards['2:3'];hover(other.title,other)
    assert other.property('highlighted') and not card.property('highlighted') and w.graph.highlighted=='2:3'
    hover(w.notice);assert w.graph.highlighted is None
    for count in (1,2,3,4):
        w.set_sim_count(count);assert len(w.state['room']['members'])==count
        assert len(w.state['edges'])==count*(count-1)//2
    for scenario in ('loss','offline','stale','normal'):
        w.set_sim_scenario(scenario);assert len(w.state['edges'])==6
    w.command('connect');w.command('capture');assert not sent
    w.toggle_simulation(False);assert not w.state.get('connected')
    w.toggle_simulation(True);w.pages.setCurrentIndex(0);w.resize(980,680);w.refresh();app.processEvents()
    w.grab().save(str(out/f'revised-compact-{scale}.png'))
    w.resize(1320,860);app.processEvents()
    for name,action in [('updates',w.update_dialog),('logs',w.logs_dialog),('dissolve',w.dissolve)]:
        action();detail=w.expansion;initial=detail.panel.geometry();settled(detail)
        assert detail.panel.geometry()==detail.target(),name+' expansion did not finish: '+str(detail.panel.geometry())+' vs '+str(detail.target())
        assert detail.panel.geometry()!=initial,name+' did not animate'
        assert not any(isinstance(x,QDialog) and x.isVisible() for x in app.topLevelWidgets())
        QTest.mouseClick(detail.panel,Qt.LeftButton,pos=QPoint(10,10));assert not detail.closing
        w.grab().save(str(out/f'expanded-{name}-{scale}.png'))
        QTest.mouseClick(detail,Qt.LeftButton,pos=QPoint(2,2));assert detail.closing
        QTest.qWait(230);assert w.expansion is None,name+' did not dismiss'
    w.logs_dialog();QTest.qWait(260);QTest.keyClick(w.expansion,Qt.Key_Escape);QTest.qWait(220);assert w.expansion is None
    w.logs_dialog();QTest.qWait(260);w.resize(1080,740);app.processEvents();assert w.expansion.panel.geometry()==w.expansion.target();w.clear_details()
    w.resize(1320,860);app.processEvents()
    rect=next(r for r,a,b in w.graph.label_hits if a=='2' and b=='3')
    QTest.mouseClick(w.graph,Qt.LeftButton,pos=rect.center().toPoint());detail=w.inline;settled(detail)
    assert w.expansion is None and detail.parentWidget() is w.graph.parentWidget()
    assert detail.geometry()==detail.destination
    w.grab().save(str(out/f'inline-route-{scale}.png'))
    choices=detail.findChildren(QPushButton,'inlineRoute');assert len(choices)==6
    assert not any(b.text() in ('游戏','协调') for b in detail.findChildren(QPushButton))
    QTest.mouseClick(choices[3],Qt.LeftButton);QTest.qWait(300);assert w.sim_modes['2:3']['game_mode']=='ipv4'
    before=choices[3].text();w.set_sim_scenario('loss');QTest.qWait(300);assert choices[3].text()!=before
    QTest.mouseClick(w.notice,Qt.LeftButton);QTest.qWait(220);assert w.inline is None
    rect=next(r for r,s in w.graph.player_hits if s=='2')
    QTest.mouseClick(w.graph,Qt.LeftButton,pos=rect.center().toPoint());detail=w.inline;settled(detail)
    field=detail.findChild(QLineEdit);field.setText('192.168.1.12');w.grab().save(str(out/f'inline-player-{scale}.png'))
    save=next(b for b in detail.findChildren(QPushButton) if b.text()=='保存');QTest.mouseClick(save,Qt.LeftButton);QTest.qWait(220)
    assert w.sim_lan['2']=='192.168.1.12' and w.inline is None
    w.resize(980,680);app.processEvents();w.edge_dialog('2','3');settled(w.inline)
    assert w.inline.parentWidget().rect().contains(w.inline.geometry());w.grab().save(str(out/f'inline-compact-{scale}.png'));w.clear_details()
    w.allow_close=True;w.close();app.processEvents()
print('PASS: settings, simulation, themes, in-place route/player expansion, live latency, direct switch, address save, outside click, resize; scale '+scale)
