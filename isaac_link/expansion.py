"""Animated in-window details, anchored to the control that opened them."""
from PySide6.QtCore import Qt,QRect,QPoint,QPropertyAnimation,QEasingCurve,Signal
from PySide6.QtGui import QColor,QPainter
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea,QLayout

class Expansion(QWidget):
    dismissed=Signal()
    def __init__(self,parent,anchor,title,width=580,height=500):
        super().__init__(parent);self.anchor=anchor;self.desired=(width,height);self.closing=False
        self.setGeometry(parent.rect());self.setFocusPolicy(Qt.StrongFocus)
        self.panel=QFrame(self);self.panel.setObjectName('expansion')
        box=QVBoxLayout(self.panel);box.setContentsMargins(20,16,20,18);box.setSizeConstraint(QLayout.SetNoConstraint)
        header=QHBoxLayout();label=QLabel(title);label.setObjectName('hero');header.addWidget(label);header.addStretch()
        close=QPushButton('收起');close.clicked.connect(self.collapse);header.addWidget(close);box.addLayout(header)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
        self.body=QWidget();self.content=QVBoxLayout(self.body);self.content.setContentsMargins(0,10,8,0);self.content.setSpacing(12);self.content.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.body);box.addWidget(scroll,1)
        self.animation=QPropertyAnimation(self.panel,b'geometry',self);self.animation.finished.connect(self.animation_done)

    def origin(self):
        try:
            rect=QRect(self.anchor.mapTo(self.parentWidget(),QPoint(0,0)),self.anchor.size())
            return rect.intersected(self.rect()) if not rect.isEmpty() else QRect(20,20,120,40)
        except RuntimeError:return QRect(20,20,120,40)

    def target(self):
        width=min(self.desired[0],self.width()-32);height=min(self.desired[1],self.height()-32);center=self.origin().center()
        return QRect(max(16,min(center.x()-width//2,self.width()-width-16)),
                     max(16,min(center.y()-height//2,self.height()-height-16)),width,height)

    def open(self):
        self.show();self.raise_();self.setFocus();self.animation.setDuration(230);self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.setStartValue(self.origin());self.animation.setEndValue(self.target());self.animation.start()

    def collapse(self):
        if self.closing:return
        self.closing=True;self.animation.stop();self.animation.setDuration(180);self.animation.setEasingCurve(QEasingCurve.InCubic)
        self.animation.setStartValue(self.panel.geometry());self.animation.setEndValue(self.origin());self.animation.start()

    def animation_done(self):
        if self.closing:self.hide();self.dismissed.emit();self.deleteLater()

    def relayout(self):
        self.setGeometry(self.parentWidget().rect())
        if not self.closing:self.animation.stop();self.panel.setGeometry(self.target())

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor(0,0,0,85))

    def mousePressEvent(self,event):
        if not self.panel.geometry().contains(event.position().toPoint()):self.collapse()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape:self.collapse()
        else:super().keyPressEvent(event)
