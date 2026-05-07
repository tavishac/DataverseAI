import pandas as pd

data = {
    "Product": ["Laptop", "Laptop", "Phone", "Tablet", "Phone"],
    "Region": ["North", "South", "East", "West", "South"],
    "Sales": [2500, 3000, 1500, 1200, 1800],
    "Month": ["January", "February", "January", "March", "April"]
}

df = pd.DataFrame(data)
df.to_excel("sample_data.xlsx", index=False)  # save as xlsx
print("sample_data.xlsx created!")
