# Desktop-Widgets

Collection of Python desktop overlay widgets and standalone applications

Built by [Naadir](https://github.com/Naadir-Dev-Portfolio)

## Overview

A comprehensive suite of desktop widgets and applications built with PyQt6 for system monitoring, financial tracking, and data visualization. Includes crypto price tickers, trading charts, news feeds, health tracking, and calculators. Widgets run as persistent overlays with real-time data integration.

## Features

- Crypto ticker and price monitoring widgets
- Trading charts (FTSE, SPY, Treasuries)
- Financial news feeds and sentiment analysis
- Health tracking dashboard with vitals
- Mortgage calculator and financial planning tools
- Network mapping and connectivity visualization
- System update monitor
- Chrome history navigator
- Google Trends integration
- Panic mode (emergency information aggregator)

## Tech Stack

Python · PyQt6 · requests · various APIs

## Setup

```
pip install -r requirements.txt
python widgets/widget_coinstats.py
```

## Structure

- `widgets/` - Individual PyQt6 overlay widgets (widget_*.py)
- `standalone-apps/` - Standalone applications (external_app_*.py)
- `Chrome-History-Navigator/` - Chrome browsing history analyzer
- `Google-Trends-PyQt/` - Google Trends data visualization

## Notes

Some widgets require API keys for financial data. Configure via environment variables.
