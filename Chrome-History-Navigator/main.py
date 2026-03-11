import webbrowser
import pandas as pd
from tkinter import Tk, messagebox
import os
import time

def open_urls_in_batches(file_path, date_filter, url_prefix, batch_size=20):
    # Check if the file exists
    if not os.path.isfile(file_path):
        print(f"File not found: {file_path}")
        return

    print(f"Loading CSV file from: {file_path}")
    try:
        data = pd.read_csv(file_path)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return
    print("CSV file loaded successfully.")

    # Print columns for debugging
    print("CSV Columns:", data.columns.tolist())

    # Convert 'date' column to datetime
    if not pd.api.types.is_datetime64_any_dtype(data['date']):
        try:
            data['date'] = pd.to_datetime(data['date'], errors='coerce')
        except Exception as e:
            print(f"Error converting 'date' column to datetime: {e}")
            return

    # Check for parsing errors
    if data['date'].isnull().any():
        print("Some dates could not be parsed. Please check the date format in the CSV.")
        return

    # Convert date_filter to datetime
    try:
        date_filter_dt = pd.to_datetime(date_filter, format="%m/%d/%Y")
    except ValueError:
        print("date_filter is not in the correct format (MM/DD/YYYY).")
        return

    # Define acceptable URL prefixes
    url_prefixes = ["https://x.com/", "http://x.com/"]

    # Filter URLs by date and prefix
    filtered_data = data[
        (data['date'] == date_filter_dt) & 
        (data['url'].str.startswith(tuple(url_prefixes)))
    ]

    urls = filtered_data['url'].tolist()
    total_urls = len(urls)
    print(f"Total URLs after filtering: {total_urls}")

    if total_urls == 0:
        print(f"No URLs found for date: {date_filter} with prefix: {url_prefix}")
        return

    # Open URLs in batches
    for i in range(0, total_urls, batch_size):
        batch = urls[i:i+batch_size]
        
        print(f"Opening batch {i//batch_size + 1}: {len(batch)} URLs")
        
        # Open the batch of URLs
        for url in batch:
            try:
                webbrowser.open(url, new=2)  # Open in a new tab
                time.sleep(0.1)  # Short delay
            except Exception as e:
                print(f"Failed to open URL {url}: {e}")
        
        # Message box to continue
        tabs_opened = min(i + batch_size, total_urls)
        if tabs_opened < total_urls:
            try:
                root = Tk()
                root.withdraw()  # Hide the root window
                response = messagebox.askyesno(
                    "Continue Opening Tabs",
                    f"{tabs_opened} out of {total_urls} tabs opened.\n"
                    f"Click 'Yes' to open the next {min(batch_size, total_urls - tabs_opened)} tabs."
                )
                root.destroy()  # Destroy the root window
                if not response:
                    print("User chose to stop opening more tabs.")
                    break
            except Exception as e:
                print(f"Error displaying message box: {e}")
                break
        else:
            try:
                root = Tk()
                root.withdraw()  # Hide the root window
                messagebox.showinfo("All Tabs Opened", f"All {total_urls} tabs have been opened.")
                root.destroy()
            except Exception as e:
                print(f"Error displaying final message box: {e}")

if __name__ == "__main__":
    try:
        # Input parameters
        file_path = r"D:\Libraries\Desktop\history.csv"  # Use the raw string for the file path
        date_filter = "12/01/2024"  # Date in MM/DD/YYYY format
        url_prefix = "https://x.com/"  # URL prefix to filter

        # Call the function
        open_urls_in_batches(file_path, date_filter, url_prefix)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
