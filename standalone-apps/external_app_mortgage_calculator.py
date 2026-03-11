#!/usr/bin/env python3
"""
Mortgage Tracker & Overpayment Calculator Application

This PyQt6 application allows you to input mortgage details, simulate
the amortization schedule with and without monthly overpayments, display
a dynamic graph of mortgage balance over time, provide a payment breakdown,
estimate the payoff date, and export your data as a PDF report. It also
supports saving/loading mortgage details to/from a local JSON file and
toggling between a dark and a light theme.

Author: [Your Name]
Date: [Today's Date]
"""

import sys
import json
import datetime
import os
from math import ceil

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QLabel, QPushButton, QFileDialog, QMessageBox, QScrollArea, QComboBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIntValidator, QDoubleValidator

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# ReportLab is used for PDF export
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later


# =============================================================================
# Mortgage Calculator Logic
# =============================================================================
class MortgageCalculator:
    """Encapsulates mortgage calculations and simulation of the amortization schedule."""
    
    @staticmethod
    def calc_monthly_payment(principal: float, annual_rate: float, term_months: int) -> float:
        """
        Calculate the fixed monthly payment required to amortize a loan.

        :param principal: The loan amount.
        :param annual_rate: The annual interest rate (in %).
        :param term_months: The total number of months over which the loan is amortized.
        :return: The monthly payment amount.
        """
        if annual_rate == 0:
            return principal / term_months
        monthly_rate = annual_rate / 100 / 12
        return principal * monthly_rate * (1 + monthly_rate) ** term_months / ((1 + monthly_rate) ** term_months - 1)

    @staticmethod
    def simulate_schedule(loan_amount: float, mortgage_term_years: int, fixed_rate: float,
                          fixed_term_years: int, remaining_rate: float, monthly_overpayment: float = 0.0):
        """
        Simulate the full amortization schedule with a two-phase (fixed then variable) interest rate.
        Returns a tuple (schedule, summary) where schedule is a list of monthly entries and summary is a dict.
        Each entry in schedule is a dict with keys: month, payment, interest, principal, overpayment, balance.
        The simulation stops when the loan is paid off.
        """
        schedule = []
        total_months = mortgage_term_years * 12
        fixed_months = min(fixed_term_years * 12, total_months)
        month = 1
        balance = loan_amount
        total_interest = 0.0

        # Phase 1: Fixed rate period
        monthly_payment_fixed = MortgageCalculator.calc_monthly_payment(loan_amount, fixed_rate, total_months)
        while month <= fixed_months and balance > 0:
            monthly_rate = fixed_rate / 100 / 12
            interest = balance * monthly_rate
            principal_component = monthly_payment_fixed - interest
            extra = monthly_overpayment
            payment = monthly_payment_fixed + extra
            # Ensure we don’t overpay
            if principal_component + extra > balance:
                principal_component = balance
                extra = 0
                payment = balance + interest

            balance = max(balance - (principal_component + extra), 0)
            total_interest += interest

            schedule.append({
                "month": month,
                "payment": payment,
                "interest": interest,
                "principal": principal_component,
                "overpayment": extra,
                "balance": balance
            })
            month += 1

        # Phase 2: Remaining period with new interest rate (if balance still remains)
        if balance > 0:
            remaining_months = total_months - fixed_months
            # Recalculate monthly payment based on the new rate and remaining term.
            # Note: In reality, the term might change if overpayments accelerate payoff.
            monthly_payment_remaining = MortgageCalculator.calc_monthly_payment(balance, remaining_rate, remaining_months)
            while balance > 0:
                monthly_rate = remaining_rate / 100 / 12
                interest = balance * monthly_rate
                principal_component = monthly_payment_remaining - interest
                extra = monthly_overpayment
                payment = monthly_payment_remaining + extra

                if principal_component + extra > balance:
                    principal_component = balance
                    extra = 0
                    payment = balance + interest

                balance = max(balance - (principal_component + extra), 0)
                total_interest += interest

                schedule.append({
                    "month": month,
                    "payment": payment,
                    "interest": interest,
                    "principal": principal_component,
                    "overpayment": extra,
                    "balance": balance
                })
                month += 1

        # Summary calculations
        months_taken = month - 1
        total_payment = sum(item["payment"] for item in schedule)
        # Estimate payoff date (approximate: assume 30 days per month)
        payoff_date = (datetime.date.today() + datetime.timedelta(days=months_taken * 30)).strftime("%Y-%m-%d")
        summary = {
            "total_interest": total_interest,
            "total_payment": total_payment,
            "months_taken": months_taken,
            "payoff_date": payoff_date,
            "time_saved_months": total_months - months_taken if months_taken < total_months else 0
        }
        return schedule, summary

    @staticmethod
    def get_payment_breakdown(schedule: list):
        """
        Aggregate the breakdown of total interest, principal, and payments over the schedule.
        """
        total_interest = sum(item["interest"] for item in schedule)
        total_principal = sum(item["principal"] for item in schedule)
        total_overpayment = sum(item["overpayment"] for item in schedule)
        total_payment = sum(item["payment"] for item in schedule)
        return {
            "total_interest": total_interest,
            "total_principal": total_principal,
            "total_overpayment": total_overpayment,
            "total_payment": total_payment
        }

# =============================================================================
# Graph Plotting Widget
# =============================================================================
class GraphCanvas(FigureCanvas):
    """Matplotlib canvas to display mortgage balance graphs."""
    
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, facecolor='#1A1A1A')
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.fig.tight_layout()

    def update_plot(self, schedule_with: list, schedule_without: list):
        """
        Update the graph with two schedules:
         - schedule_with: with overpayments.
         - schedule_without: without overpayments.
        """
        self.ax.clear()
        self.ax.set_facecolor('#101010')
        self.fig.patch.set_facecolor('#1A1A1A')
        
        # Prepare x (month) and y (balance) data
        months_with = [item["month"] for item in schedule_with]
        balance_with = [item["balance"] for item in schedule_with]
        months_without = [item["month"] for item in schedule_without]
        balance_without = [item["balance"] for item in schedule_without]
        
        self.ax.plot(months_without, balance_without, label="Without Overpayments", color="#5E5E5E", linewidth=2)
        self.ax.plot(months_with, balance_with, label="With Overpayments", color="#3E8E41", linewidth=2)
        
        self.ax.set_xlabel("Month", color="white")
        self.ax.set_ylabel("Remaining Balance (£)", color="white")
        self.ax.tick_params(axis='x', colors='white')
        self.ax.tick_params(axis='y', colors='white')
        self.ax.legend(facecolor='#2F2F2F', edgecolor='white', labelcolor='white')
        self.draw()

# =============================================================================
# File Handling (Save & Load)
# =============================================================================
class FileHandler:
    """Handles saving and loading mortgage data as JSON."""
    
    @staticmethod
    def save_data(data: dict, filename: str):
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
    
    @staticmethod
    def load_data(filename: str) -> dict:
        with open(filename, 'r') as f:
            data = json.load(f)
        return data

# =============================================================================
# PDF Report Exporter
# =============================================================================
class ReportExporter:
    """Exports the mortgage calculations and graph as a PDF report using ReportLab."""
    
    @staticmethod
    def export_pdf(filename: str, inputs: dict, summary: dict, breakdown: dict, graph_canvas: GraphCanvas):
        c = canvas.Canvas(filename, pagesize=letter)
        width, height = letter
        
        # Title
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width / 2, height - 50, "Mortgage Report")
        
        # Inputs section
        c.setFont("Helvetica", 12)
        textobject = c.beginText(50, height - 80)
        textobject.textLine("Mortgage Details:")
        for key, value in inputs.items():
            textobject.textLine(f"  {key}: {value}")
        c.drawText(textobject)
        
        # Summary section
        textobject = c.beginText(50, height - 180)
        textobject.textLine("Mortgage Summary:")
        for key, value in summary.items():
            textobject.textLine(f"  {key}: {value}")
        c.drawText(textobject)
        
        # Payment breakdown
        textobject = c.beginText(50, height - 260)
        textobject.textLine("Payment Breakdown:")
        for key, value in breakdown.items():
            textobject.textLine(f"  {key}: {round(value,2)}")
        c.drawText(textobject)
        
        # Save the current graph to a temporary file and embed it.
        temp_graph = "temp_graph.png"
        graph_canvas.fig.savefig(temp_graph)
        c.drawImage(temp_graph, 50, height - 500, width=500, height=200)
        os.remove(temp_graph)
        
        c.showPage()
        c.save()

# =============================================================================
# Main Application Window
# =============================================================================
class MortgageTrackerWindow(QMainWindow):
    """Main window for the Mortgage Tracker & Overpayment Calculator."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mortgage Tracker & Overpayment Calculator")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnBottomHint
        )
        self.resize(1000, 800)
        self.current_theme = "dark"  # default mode

        # Main container widget
        self.container = QWidget()
        self.setCentralWidget(self.container)
        self.layout = QVBoxLayout(self.container)

        # Create input form and output area
        self.create_input_fields()
        self.create_output_labels()
        self.create_buttons()
        self.create_graph()

        # Timer for debouncing input updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.update_calculations)

        self.apply_theme()  # Apply initial dark theme
        hide_from_taskbar_later(self)

    def create_input_fields(self):
        """Create input fields for mortgage details."""
        grid = QGridLayout()
        row = 0
        
        # House Price
        self.house_price_edit = QLineEdit()
        self.house_price_edit.setPlaceholderText("e.g., 300000")
        self.house_price_edit.setValidator(QDoubleValidator(0.0, 1e9, 2))
        grid.addWidget(QLabel("House Price (£):"), row, 0)
        grid.addWidget(self.house_price_edit, row, 1)
        row += 1

        # Deposit
        self.deposit_edit = QLineEdit()
        self.deposit_edit.setPlaceholderText("e.g., 60000")
        self.deposit_edit.setValidator(QDoubleValidator(0.0, 1e9, 2))
        grid.addWidget(QLabel("Deposit (£):"), row, 0)
        grid.addWidget(self.deposit_edit, row, 1)
        row += 1

        # Mortgage Term (Years)
        self.term_edit = QLineEdit()
        self.term_edit.setPlaceholderText("e.g., 30")
        self.term_edit.setValidator(QIntValidator(1, 100))
        grid.addWidget(QLabel("Mortgage Term (Years):"), row, 0)
        grid.addWidget(self.term_edit, row, 1)
        row += 1

        # Fixed-Term Interest Rate (%)
        self.fixed_rate_edit = QLineEdit()
        self.fixed_rate_edit.setPlaceholderText("e.g., 4.6")
        self.fixed_rate_edit.setValidator(QDoubleValidator(0.0, 100.0, 2))
        grid.addWidget(QLabel("Fixed-Term Interest Rate (%):"), row, 0)
        grid.addWidget(self.fixed_rate_edit, row, 1)
        row += 1

        # Fixed-Term Duration (Years)
        self.fixed_term_edit = QLineEdit()
        self.fixed_term_edit.setPlaceholderText("e.g., 3")
        self.fixed_term_edit.setValidator(QIntValidator(1, 100))
        grid.addWidget(QLabel("Fixed-Term Duration (Years):"), row, 0)
        grid.addWidget(self.fixed_term_edit, row, 1)
        row += 1

        # Remaining Term Interest Rate (%)
        self.remaining_rate_edit = QLineEdit()
        self.remaining_rate_edit.setPlaceholderText("e.g., 5.5")
        self.remaining_rate_edit.setValidator(QDoubleValidator(0.0, 100.0, 2))
        grid.addWidget(QLabel("Remaining Term Interest Rate (%):"), row, 0)
        grid.addWidget(self.remaining_rate_edit, row, 1)
        row += 1

        # Monthly Overpayment
        self.overpayment_edit = QLineEdit()
        self.overpayment_edit.setPlaceholderText("e.g., 200")
        self.overpayment_edit.setValidator(QDoubleValidator(0.0, 1e9, 2))
        grid.addWidget(QLabel("Monthly Overpayment (£):"), row, 0)
        grid.addWidget(self.overpayment_edit, row, 1)
        row += 1

        # Calculated Loan Amount (read-only)
        self.loan_amount_label = QLabel("Loan Amount (£): 0.00")
        grid.addWidget(self.loan_amount_label, row, 0, 1, 2)
        row += 1

        self.layout.addLayout(grid)

        # Connect input changes to update timer
        for widget in [self.house_price_edit, self.deposit_edit, self.term_edit, self.fixed_rate_edit,
                       self.fixed_term_edit, self.remaining_rate_edit, self.overpayment_edit]:
            widget.textChanged.connect(self.start_update_timer)

    def create_output_labels(self):
        """Create labels to display calculation results."""
        self.results_label = QLabel("Monthly Payment, Total Interest, Payoff Date, etc. will be displayed here.")
        self.results_label.setWordWrap(True)
        self.layout.addWidget(self.results_label)

    def create_buttons(self):
        """Create buttons for Save, Load, Export Report, and Theme Toggle."""
        btn_layout = QHBoxLayout()
        self.save_button = QPushButton("Save Data")
        self.save_button.clicked.connect(self.save_data)
        btn_layout.addWidget(self.save_button)

        self.load_button = QPushButton("Load Data")
        self.load_button.clicked.connect(self.load_data)
        btn_layout.addWidget(self.load_button)

        self.export_button = QPushButton("Export PDF Report")
        self.export_button.clicked.connect(self.export_report)
        btn_layout.addWidget(self.export_button)

        self.theme_toggle_button = QPushButton("Toggle Light/Dark Mode")
        self.theme_toggle_button.clicked.connect(self.toggle_theme)
        btn_layout.addWidget(self.theme_toggle_button)

        self.layout.addLayout(btn_layout)

    def create_graph(self):
        """Create the mortgage balance graph area."""
        self.graph_canvas = GraphCanvas(self, width=8, height=4, dpi=100)
        self.layout.addWidget(self.graph_canvas)

    def start_update_timer(self):
        """Debounce rapid input changes."""
        self.update_timer.start(500)

    def update_calculations(self):
        """Read inputs, perform calculations, update labels and graph."""
        try:
            house_price = float(self.house_price_edit.text() or 0)
            deposit = float(self.deposit_edit.text() or 0)
            term_years = int(self.term_edit.text() or 0)
            fixed_rate = float(self.fixed_rate_edit.text() or 0)
            fixed_term = int(self.fixed_term_edit.text() or 0)
            remaining_rate = float(self.remaining_rate_edit.text() or 0)
            monthly_overpayment = float(self.overpayment_edit.text() or 0)
        except ValueError:
            return

        if house_price <= deposit or term_years <= 0:
            self.results_label.setText("Please ensure the House Price is greater than Deposit and Term > 0.")
            return

        loan_amount = house_price - deposit
        self.loan_amount_label.setText(f"Loan Amount (£): {loan_amount:,.2f}")

        # Simulation with overpayments
        schedule_over, summary_over = MortgageCalculator.simulate_schedule(
            loan_amount, term_years, fixed_rate, fixed_term, remaining_rate, monthly_overpayment
        )
        breakdown_over = MortgageCalculator.get_payment_breakdown(schedule_over)

        # Simulation without overpayments
        schedule_no, summary_no = MortgageCalculator.simulate_schedule(
            loan_amount, term_years, fixed_rate, fixed_term, remaining_rate, monthly_overpayment=0
        )
        breakdown_no = MortgageCalculator.get_payment_breakdown(schedule_no)

        # Prepare result summary text
        result_text = (
            f"<b>With Overpayments:</b><br>"
            f"Monthly Payment (Phase 1 based on full term): {MortgageCalculator.calc_monthly_payment(loan_amount, fixed_rate, term_years*12):,.2f} <br>"
            f"Total Interest Paid: {breakdown_over['total_interest']:,.2f} <br>"
            f"Total Payment: {breakdown_over['total_payment']:,.2f} <br>"
            f"Loan Paid Off in: {summary_over['months_taken']} months <br>"
            f"Estimated Payoff Date: {summary_over['payoff_date']} <br>"
            f"Time Saved: {summary_over['time_saved_months']} months <br><br>"
            f"<b>Without Overpayments:</b><br>"
            f"Total Interest Paid: {breakdown_no['total_interest']:,.2f} <br>"
            f"Total Payment: {breakdown_no['total_payment']:,.2f} <br>"
        )
        self.results_label.setText(result_text)

        # Update graph
        self.graph_canvas.update_plot(schedule_over, schedule_no)

    def save_data(self):
        """Save current mortgage details to a JSON file."""
        inputs = self.get_input_data()
        filename, _ = QFileDialog.getSaveFileName(self, "Save Mortgage Data", "", "JSON Files (*.json)")
        if filename:
            try:
                FileHandler.save_data(inputs, filename)
                QMessageBox.information(self, "Save Data", "Data saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save data: {e}")

    def load_data(self):
        """Load mortgage details from a JSON file."""
        filename, _ = QFileDialog.getOpenFileName(self, "Load Mortgage Data", "", "JSON Files (*.json)")
        if filename:
            try:
                data = FileHandler.load_data(filename)
                self.set_input_data(data)
                self.update_calculations()
                QMessageBox.information(self, "Load Data", "Data loaded successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load data: {e}")

    def export_report(self):
        """Export a PDF report with the current mortgage data and graph."""
        filename, _ = QFileDialog.getSaveFileName(self, "Export PDF Report", "", "PDF Files (*.pdf)")
        if filename:
            # Gather current input and summary details
            inputs = self.get_input_data()
            house_price = float(self.house_price_edit.text() or 0)
            deposit = float(self.deposit_edit.text() or 0)
            loan_amount = house_price - deposit
            term_years = int(self.term_edit.text() or 0)
            fixed_rate = float(self.fixed_rate_edit.text() or 0)
            fixed_term = int(self.fixed_term_edit.text() or 0)
            remaining_rate = float(self.remaining_rate_edit.text() or 0)
            monthly_overpayment = float(self.overpayment_edit.text() or 0)

            schedule_over, summary_over = MortgageCalculator.simulate_schedule(
                loan_amount, term_years, fixed_rate, fixed_term, remaining_rate, monthly_overpayment
            )
            breakdown_over = MortgageCalculator.get_payment_breakdown(schedule_over)
            try:
                ReportExporter.export_pdf(filename, inputs, summary_over, breakdown_over, self.graph_canvas)
                QMessageBox.information(self, "Export Report", "PDF report exported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export report: {e}")

    def get_input_data(self) -> dict:
        """Retrieve current input data as a dictionary."""
        return {
            "House Price": self.house_price_edit.text(),
            "Deposit": self.deposit_edit.text(),
            "Mortgage Term (Years)": self.term_edit.text(),
            "Fixed-Term Interest Rate (%)": self.fixed_rate_edit.text(),
            "Fixed-Term Duration (Years)": self.fixed_term_edit.text(),
            "Remaining Term Interest Rate (%)": self.remaining_rate_edit.text(),
            "Monthly Overpayment": self.overpayment_edit.text()
        }

    def set_input_data(self, data: dict):
        """Set the input fields from a data dictionary."""
        self.house_price_edit.setText(data.get("House Price", ""))
        self.deposit_edit.setText(data.get("Deposit", ""))
        self.term_edit.setText(data.get("Mortgage Term (Years)", ""))
        self.fixed_rate_edit.setText(data.get("Fixed-Term Interest Rate (%)", ""))
        self.fixed_term_edit.setText(data.get("Fixed-Term Duration (Years)", ""))
        self.remaining_rate_edit.setText(data.get("Remaining Term Interest Rate (%)", ""))
        self.overpayment_edit.setText(data.get("Monthly Overpayment", ""))

    def toggle_theme(self):
        """Toggle between dark and light modes."""
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme()

    def apply_theme(self):
        """Apply the current theme using QSS stylesheets."""
        if self.current_theme == "dark":
            style = """
            QWidget {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #101010, stop:1 #1A1A1A);
                color: white;
                font-family: Arial;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #2F2F2F;
                border: 1px solid #3E3E3E;
                padding: 4px;
                color: white;
            }
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(60,60,60,0.95), stop:1 rgba(40,40,40,0.95));
                border: none;
                padding: 6px;
                border-radius: 4px;
                color: white;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(70,70,70,0.95), stop:1 rgba(50,50,50,0.95));
            }
            QPushButton:pressed {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(50,50,50,0.95), stop:1 rgba(30,30,30,0.95));
            }
            QPushButton:disabled {
                background-color: rgba(80,80,80,0.95);
                color: rgba(200,200,200,0.7);
            }
            QScrollBar:vertical {
                background: rgba(60,60,60,0.95);
                width: 12px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(40,40,40,0.95);
                border-radius: 6px;
            }
            QProgressBar {
                border: 1px solid #3E3E3E;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3E3E3E, stop:1 #5E5E5E);
                border-radius: 5px;
            }
            """
        else:
            # Light mode style
            style = """
            QWidget {
                background-color: #F0F0F0;
                color: #202020;
                font-family: Arial;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #AAAAAA;
                padding: 4px;
                color: #202020;
            }
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #DDDDDD, stop:1 #BBBBBB);
                border: none;
                padding: 6px;
                border-radius: 4px;
                color: #202020;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #EEEEEE, stop:1 #CCCCCC);
            }
            QPushButton:pressed {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #CCCCCC, stop:1 #AAAAAA);
            }
            QPushButton:disabled {
                background-color: #BBBBBB;
                color: #888888;
            }
            QScrollBar:vertical {
                background: #DDDDDD;
                width: 12px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #BBBBBB;
                border-radius: 6px;
            }
            QProgressBar {
                border: 1px solid #AAAAAA;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #AAAAAA, stop:1 #888888);
                border-radius: 5px;
            }
            """
        self.setStyleSheet(style)

# =============================================================================
# Main Execution
# =============================================================================
def main():
    app = QApplication(sys.argv)
    window = MortgageTrackerWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
