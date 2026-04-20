#!/usr/bin/env python3
import akshare as ak

df = ak.stock_zh_a_spot()
print("Columns:", list(df.columns))
print("\nFirst row sample:")
print(df.iloc[0])
