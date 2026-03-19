"""
Custom widgets and UI helper functions
"""
from PySide6.QtGui import QPixmap, QColor, QPainter, QPen, QLinearGradient, QIcon
from PySide6.QtCore import Qt, QPoint


def create_studio_mic_icon():
    """Create a modern studio microphone icon for the tray"""
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("transparent"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    # Mic body (upper rounded part)
    mic_head_x = size * 0.35
    mic_head_y = size * 0.15
    mic_head_w = size * 0.3
    mic_head_h = size * 0.4

    # Gradient for mic head - metallic look
    head_gradient = QLinearGradient(mic_head_x, mic_head_y, mic_head_x, mic_head_y + mic_head_h)
    head_gradient.setColorAt(0.0, QColor("#58a6ff"))      # Blue highlight
    head_gradient.setColorAt(0.5, QColor("#4a9eff"))      # Mid-tone blue
    head_gradient.setColorAt(1.0, QColor("#1f6feb"))      # Dark blue shadow

    painter.setBrush(head_gradient)
    painter.setPen(QPen(QColor("#30363d"), 1))
    painter.drawRoundedRect(
        int(mic_head_x), int(mic_head_y),
        int(mic_head_w), int(mic_head_h),
        int(mic_head_w * 0.25), int(mic_head_w * 0.25)
    )

    # Grille lines on microphone head - vertical
    grille_color = QColor("#0d1117")
    grille_color.setAlpha(180)
    grille_pen = QPen(grille_color, 2)
    painter.setPen(grille_pen)

    grille_spacing = mic_head_w / 5
    for i in range(1, 5):
        grille_x = mic_head_x + grille_spacing * i
        painter.drawLine(
            int(grille_x),
            int(mic_head_y + mic_head_h * 0.1),
            int(grille_x),
            int(mic_head_y + mic_head_h * 0.9)
        )

    # Grille lines - horizontal
    grille_h_spacing = mic_head_h / 8
    for i in range(1, 8):
        grille_y = mic_head_y + grille_h_spacing * i
        painter.drawLine(
            int(mic_head_x + mic_head_w * 0.1),
            int(grille_y),
            int(mic_head_x + mic_head_w * 0.9),
            int(grille_y)
        )

    # Mic stand connector (tapered neck)
    neck_top_w = mic_head_w * 0.4
    neck_bot_w = mic_head_w * 0.6
    neck_top_x = mic_head_x + (mic_head_w - neck_top_w) / 2
    neck_top_y = mic_head_y + mic_head_h
    neck_bot_x = mic_head_x + (mic_head_w - neck_bot_w) / 2
    neck_bot_y = size * 0.65

    neck_gradient = QLinearGradient(0, neck_top_y, 0, neck_bot_y)
    neck_gradient.setColorAt(0.0, QColor("#1f6feb"))
    neck_gradient.setColorAt(1.0, QColor("#0d1117"))
    painter.setBrush(neck_gradient)
    painter.setPen(QPen(QColor("#30363d"), 1))

    points = [
        QPoint(int(neck_top_x), int(neck_top_y)),
        QPoint(int(neck_top_x + neck_top_w), int(neck_top_y)),
        QPoint(int(neck_bot_x + neck_bot_w), int(neck_bot_y)),
        QPoint(int(neck_bot_x), int(neck_bot_y)),
    ]
    painter.drawPolygon(points)

    # Speaker/cable end (bottom)
    speaker_x = size * 0.32
    speaker_y = size * 0.65
    speaker_w = size * 0.36
    speaker_h = size * 0.2

    speaker_gradient = QLinearGradient(speaker_x, speaker_y, speaker_x, speaker_y + speaker_h)
    speaker_gradient.setColorAt(0.0, QColor("#1a1a2e"))
    speaker_gradient.setColorAt(1.0, QColor("#0d0d1a"))
    painter.setBrush(speaker_gradient)
    painter.setPen(QPen(QColor("#30363d"), 1))
    painter.drawRoundedRect(
        int(speaker_x), int(speaker_y),
        int(speaker_w), int(speaker_h),
        int(speaker_w * 0.15), int(speaker_w * 0.15)
    )

    # Power indicator light
    light_x = size * 0.5 - 8
    light_y = size * 0.78
    light_color = QColor("#00d9ff")
    light_color.setAlpha(255)
    painter.setBrush(light_color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(int(light_x), int(light_y), 16, 16)

    painter.end()
    return QIcon(pixmap)
