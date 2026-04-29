import os
import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

load_dotenv()

api_key = os.getenv("ENTSOE_API_KEY")

if not api_key:
    raise ValueError("ENTSOE_API_KEY not found. Check your .env file.")

client = EntsoePandasClient(api_key=api_key)

start = pd.Timestamp.now(tz="Europe/Brussels") - pd.Timedelta(days=7)
end = pd.Timestamp.now(tz="Europe/Brussels")

country_code = "HU"

prices = client.query_day_ahead_prices(
    country_code,
    start=start,
    end=end
)

print(prices.tail())