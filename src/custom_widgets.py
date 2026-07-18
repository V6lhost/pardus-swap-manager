from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPainterPath

# color variables and fonts for testing purposes. to do: Add automatic theming support.
color_gauge_bg = "#202529"
color_gauge_fg = "#3daee9"
color_text = "#eff0f1"
font_text = "Segoe UI"
color_red_danger = "#e74c3c"
color_orange_warning = "#ffa500"
color_green_safe = "#27ae60"

class CircularStatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0
        self.used_str = "0 B"
        self.total_str = "0 B"
    
    def set_values(self, value, used, total):
        self.value = value
        self.used_str = used
        self.total_str = total

        # graph update function call
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # dynamic size calculation
        width = self.width()
        height = self.height()
        size = min(width, height) - 20
        
        rect = QRectF((width - size) / 2, (height - size) / 2, size, size)
        pen_width = size * 0.08 # thickness amount
        
        # base background circle
        bg_pen = QPen(QColor(color_gauge_bg), pen_width)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawEllipse(rect)

        # usage gauge
        if self.value > 0:
            # different colors for different percentages
            if self.value > 80:
                color_gauge = color_red_danger
            elif self.value > 50:
                color_gauge = color_orange_warning
            else:
                color_gauge = color_green_safe

            fg_pen = QPen(QColor(color_gauge), pen_width)
            fg_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(fg_pen)
            
            # starting point and direction
            start_angle =180 * 16
            span_angle = int(-(self.value / 100.0) * 360 * 16)
            painter.drawArc(rect, start_angle,span_angle)
        
        # middle labels
        painter.setPen(QColor(color_text)) # text color
        base_font_size = max(8, int(size * 0.08)) # text size

        # used label
        font_used = QFont(font_text, int(base_font_size * 0.8))
        painter.setFont(font_used)

        rect_used = QRectF(rect.x(), rect.y() + size * 0.2, size, size * 0.2)
        painter.drawText(rect_used, Qt.AlignCenter, "Used")

        # used size label
        font_val = QFont(font_text, base_font_size, QFont.Bold)
        painter.setFont(font_val)
        
        rect_val = QRectF(rect.x(), rect.y() + size * 0.38, size, size * 0.2)
        painter.drawText(rect_val, Qt.AlignCenter, self.used_str)

        # separator
        line_pen = QPen(QColor(color_gauge_fg), 1)
        painter.setPen(line_pen)
        line_y = rect.y() + size * 0.6
        painter.drawLine(rect.x() + size * 0.25, line_y, rect.x() + size * 0.75, line_y)
        
        # total size label
        painter.setPen(QColor(color_text))
        font_total = QFont(font_text, base_font_size)
        painter.setFont(font_total)
        rect_total = QRectF(rect.x(), rect.y() + size * 0.62, size, size * 0.2)
        painter.drawText(rect_total, Qt.AlignCenter, self.total_str)

        # total label
        font_lbl_total = QFont(font_text, int(base_font_size * 0.8))
        painter.setFont(font_lbl_total)
        rect_lbl_total = QRectF(rect.x(), rect.y() + size * 0.78, size, size * 0.15)
        painter.drawText(rect_lbl_total, Qt.AlignCenter, "Total")

class SpinnerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.color = QColor(color_gauge_fg)
        self.setFixedSize(40, 40) # Spinner size

        # Animation timer ~60fps
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)

    def start(self):
        self.timer.start(16)
        self.show()

    def stop(self):
        self.timer.stop()
        self.hide()

    def rotate(self):
        # Move the bar 5 degrees per step
        self.angle = (self.angle + 5) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing) # Smooth edges

        width = self.width()
        height = self.height()
        size = min(width, height) - 6
        
        # Draw area
        rect = QRectF(3, 3, size, size)

        # Pen color, thickness and smoothing
        pen = QPen()
        pen.setColor(self.color)
        pen.setWidth(4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Rotate the painter for rotating effect
        painter.translate(width / 2, height / 2)
        painter.rotate(self.angle)
        painter.translate(-width / 2, -height / 2)

        # Open spinner
        painter.drawArc(rect, 0 * 16, 270 * 16)

class ProgressbarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.minimum = 0
        self.maximum = 100
        self.value = 0
        
        # Design settings
        self.bg_color = QColor(color_gauge_bg)      # Background
        self.progress_color = QColor("#3b82f6") # Progressbar
        self.line_thickness = 4                 # Thickness
        
        # Set widget height using thickness value
        self.setFixedHeight(self.line_thickness + 6) # Extra size for better fit

    def setRange(self, min_val, max_val):
        self.minimum = min_val
        self.maximum = max_val
        self.update()

    def setValue(self, val):
        # Stay values between minimum and maximum
        self.value = max(self.minimum, min(val, self.maximum))
        self.update() # Draw again

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw limits
        width = self.width()
        height = self.height()
        
        # Center horizontally
        y_center = height / 2

        pen = QPen()
        pen.setWidth(self.line_thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap) # Make round ends

        # 1. Draw background
        pen.setColor(self.bg_color)
        painter.setPen(pen)

        # Set widget with using thickness value
        padding = self.line_thickness / 2
        painter.drawLine(padding, y_center, width - padding, y_center)

        # 2. Draw the progressbar
        if self.maximum - self.minimum > 0:
            # Calculate progress
            progress_ratio = (self.value - self.minimum) / (self.maximum - self.minimum)
            progress_width = padding + (width - 2 * padding) * progress_ratio
            
            if progress_width > padding:
                pen.setColor(self.progress_color)
                painter.setPen(pen)
                painter.drawLine(padding, y_center, progress_width, y_center)