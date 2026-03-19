"""
Mic → Push-To-Talk (Multi-Mode)
Main entry point - FIXED initialization order
"""
import sys
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtGui import QFont, QPalette, QColor

from app.config import setup_logging, DEFAULT_THEME
from app.ui.main_window import MainWindow
from app.ui.widgets import create_studio_mic_icon
from app.core.controller import Application


def setup_app_style(app):
    """Setup application style and theme"""
    # Set global font
    app.setFont(QFont("Segoe UI", 9))

    # Modern dark theme palette
    palette = QPalette()
    palette.setColor(QPalette.WindowText, QColor("#c9d1d9"))
    palette.setColor(QPalette.Window, QColor("#0d1117"))
    palette.setColor(QPalette.Base, QColor("#0d1117"))
    palette.setColor(QPalette.AlternateBase, QColor("#161b22"))
    palette.setColor(QPalette.ToolTipBase, QColor("#0d1117"))
    palette.setColor(QPalette.ToolTipText, QColor("#c9d1d9"))
    palette.setColor(QPalette.Text, QColor("#c9d1d9"))
    palette.setColor(QPalette.Button, QColor("#161b22"))
    palette.setColor(QPalette.ButtonText, QColor("#c9d1d9"))
    palette.setColor(QPalette.Link, QColor("#58a6ff"))
    palette.setColor(QPalette.Highlight, QColor("#1f6feb"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    app.setStyleSheet("""
        QMainWindow {
            background-color: #0d1117;
        }

        QWidget {
            background-color: #0d1117;
            color: #c9d1d9;
            font-size: 13px;
            font-family: 'Segoe UI', 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        QTabWidget::pane {
            border: 1px solid #30363d;
            border-radius: 6px;
            background-color: #0d1117;
        }

        QTabBar::tab {
            background: #161b22;
            padding: 8px 20px;
            border-radius: 6px 6px 0px 0px;
            border: 1px solid #30363d;
            margin-right: 2px;
        }

        QTabBar::tab:selected {
            background: #0d1117;
            border-bottom: 2px solid #58a6ff;
            color: #58a6ff;
            font-weight: 600;
        }

        QLabel {
            font-weight: 500;
            color: #c9d1d9;
        }

        QComboBox {
            background: #0d1117;
            border: 2px solid #30363d;
            padding: 6px 8px;
            border-radius: 6px;
            color: #c9d1d9;
            margin: 0px;
            padding-right: 24px;
        }

        QComboBox QAbstractItemView {
            background: #161b22;
            selection-background-color: #58a6ff;
            color: #c9d1d9;
            border: 2px solid #30363d;
            border-radius: 4px;
            outline: none;
            padding: 4px;
        }

        QPushButton {
            background-color: #238636;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            min-height: 28px;
        }

        QPushButton:hover {
            background-color: #2ea043;
        }

        QPushButton:pressed {
            background-color: #1f6feb;
        }

        QSlider::groove:horizontal {
            height: 6px;
            background: #30363d;
            border: 1px solid #30363d;
            border-radius: 3px;
        }

        QSlider::handle:horizontal {
            background: #58a6ff;
            width: 16px;
            margin: -5px 0;
            border-radius: 8px;
        }

        QSpinBox {
            background: #0d1117;
            border: 1px solid #30363d;
            padding: 4px 6px;
            border-radius: 4px;
            color: #c9d1d9;
            min-width: 50px;
        }

        QTextEdit {
            background: #0d1117;
            border: 1px solid #30363d;
            color: #c9d1d9;
            border-radius: 6px;
        }

        QListWidget {
            background: #0d1117;
            border: 1px solid #30363d;
            color: #c9d1d9;
            border-radius: 6px;
        }

        QListWidget::item:selected {
            background: #58a6ff;
            color: #0d1117;
        }
    """)


def main():
    """Application entry point"""
    setup_logging()
    
    # ===== CORRECT ORDER =====
    # Step 1: Create Qt application
    qt_app = QApplication(sys.argv)
    
    # Step 2: Setup style BEFORE creating windows
    setup_app_style(qt_app)
    
    # Step 3: Set application icon
    qt_app.setWindowIcon(create_studio_mic_icon())
    
    # Step 4: Create main window WITHOUT parent_app yet
    # (we'll assign it after creating the controller)
    window = MainWindow(parent_app=None)
    
    # Step 5: Create the Application controller with the window
    # This is the ONLY place we create Application
    controller = Application(qt_app, window)
    
    # Step 6: Now assign the controller to the window
    # So window.parent_app points to the right controller
    window.parent_app = controller
    
    # Step 7: Initialize microphone on startup
    # (after window and controller are both ready)
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500, window.initialize_microphone_ui)
    
    # Step 8: Show window
    window.show()
    
    # Step 9: Setup tray icon
    tray_icon = QSystemTrayIcon(create_studio_mic_icon())
    tray_icon.setToolTip("Mic → Push-To-Talk (Multi-Mode)")
    tray_icon.show()
    
    # Step 10: Handle window close
    def on_close():
        controller.shutdown()
        qt_app.quit()
    
    window.closeEvent = lambda event: (on_close(), event.accept())
    
    # Step 11: Run application
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
