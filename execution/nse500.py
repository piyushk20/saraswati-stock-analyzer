import requests
import pandas as pd
from io import StringIO
import json

def analyze_tables():
    url = "https://en.wikipedia.org/wiki/NIFTY_500"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    tables = pd.read_html(StringIO(response.text))
    for i, df in enumerate(tables):
        print(f"Table {i} columns:", df.columns.tolist())

if __name__ == "__main__":
    analyze_tables()
