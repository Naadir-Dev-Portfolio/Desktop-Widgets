import sys
import webbrowser
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('Google Trends - AI')

        # Create a button to open Google Trends
        button = QPushButton('Open Google Trends for AI')
        button.clicked.connect(self.open_trends)

        # Set layout
        central_widget = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(button)
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        # Set the window size
        self.resize(400, 200)

    def open_trends(self):
        # URL for Google Trends AI search
        url = 'https://trends.google.com/trends/explore?q=ai'
        webbrowser.open(url)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
