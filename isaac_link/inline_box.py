"""A topology label grows in place; no scrim or separate detail window."""
from PySide6.QtCore import Qt,QEvent,QRect,QPropertyAnimation,QEasingCurve,Signal
from PySide6.QtWidgets import QApplication,QFrame,QVBoxLayout,QLayout

class InlineBox(QFrame):
    dismissed=Signal()
    def __init__(self,parent,origin,width,height):
        super().__init__(parent);self.setObjectName('inlineDetail');self.origin=QRect(origin);self.closing=False
        width=min(width,parent.width()-16);height=min(height,parent.height()-16)
        self.destination=QRect(max(8,min(origin.center().x()-width//2,parent.width()-width-8)),
                               max(8,min(origin.center().y()-height//2,parent.height()-height-8)),width,height)
        self.content=QVBoxLayout(self);self.content.setContentsMargins(10,8,10,8);self.content.setSpacing(5);self.content.setSizeConstraint(QLayout.SetNoConstraint)
        self.animation=QPropertyAnimation(self,b'geometry',self);self.animation.finished.connect(self.done)
        QApplication.instance().installEventFilter(self)
    def open(self):
        self.setGeometry(self.origin);self.show();self.raise_();self.animation.setDuration(200);self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.setStartValue(self.origin);self.animation.setEndValue(self.destination);self.animation.start()
    def collapse(self):
        if self.closing:return
        self.closing=True;self.animation.stop();self.animation.setDuration(160);self.animation.setEasingCurve(QEasingCurve.InCubic)
        self.animation.setStartValue(self.geometry());self.animation.setEndValue(self.origin);self.animation.start()
    def done(self):
        if self.closing:self.hide();self.dismissed.emit();self.deleteLater()
    def eventFilter(self,watched,event):
        if not self.isVisible() or self.closing:return False
        if event.type()==QEvent.MouseButtonPress:
            if not self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint())):self.collapse()
        elif event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape:self.collapse();return True
        return False
