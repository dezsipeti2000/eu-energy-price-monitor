import os
from datetime import date, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GIE_API_KEY")

if not api_key:
    raise ValueError("GIE_API_KEY not found. Check your .env file.")

end_date = date.today()
start_date = end_date - timedelta(days=30)

url = "https://agsi.gie.eu/api"

params = {
    "type": "eu",
    "from": start_date.isoformat(),
    "to": end_date.isoformat(),
    "size": 300,
    "page": 1,
}

headers = {
    "x-key": api_key
}

response = requests.get(
    url,
    params=params,
    headers=headers,
    timeout=30
)

response.raise_for_status()

json_data = response.json()
data = json_data.get("data", [])

if not data:
    raise ValueError("No data returned from GIE API.")

df = pd.DataFrame(data)

print("Available columns:")
print(df.columns.tolist())

# Convert date column
if "gasDayStart" in df.columns:
    df["gasDayStart"] = pd.to_datetime(df["gasDayStart"])

# Convert numeric columns if they exist
numeric_columns = [
    "gasInStorage",
    "workingGasVolume",
    "injection",
    "withdrawal",
    "full",
]

for col in numeric_columns:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

columns_to_show = [
    col for col in [
        "gasDayStart",
        "gasInStorage",
        "workingGasVolume",
        "full",
        "injection",
        "withdrawal"
    ]
    if col in df.columns
]

print("\nLatest GIE AGSI data:")
print(df[columns_to_show].tail())