import pandas as pd
import os

data_dir = os.path.join(os.path.dirname(__file__), "data")

df1 = pd.read_csv(os.path.join(data_dir, "dataset1.csv"))
df2 = pd.read_csv(os.path.join(data_dir, "dataset2.csv"))
df3 = pd.read_csv(os.path.join(data_dir, "dataset3.csv"))

combined = df1.merge(df2, on=["category", "year2"]).merge(df3, on=["category", "year3"])
combined = combined[["category", "year1", "year2", "year3", "year4"]]

output_path = os.path.join(data_dir, "combined-data.csv")
combined.to_csv(output_path, index=False)

print(f"Merged {len(combined)} rows into {output_path}")
print(combined.to_string(index=False))
