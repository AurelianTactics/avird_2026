'''
EDA utils related to SGO dataset
'''
import os
import pandas as pd


def load_and_concat_csvs(paths):
    dfs = [pd.read_csv(p) for p in paths]
    names = [os.path.basename(p) for p in paths]

    base_name, base_df = names[0], dfs[0]
    for name, df in zip(names[1:], dfs[1:]):
        base_cols = set(base_df.columns)
        cols = set(df.columns)

        only_in_base = sorted(base_cols - cols)
        only_in_other = sorted(cols - base_cols)
        if only_in_base:
            print(f"Only in {base_name}:")
            for c in only_in_base:
                print(f"  {c}")
        if only_in_other:
            print(f"Only in {name}:")
            for c in only_in_other:
                print(f"  {c}")

        for col in sorted(base_cols & cols):
            if base_df[col].dtype != df[col].dtype:
                print(
                    f"Dtype mismatch '{col}': "
                    f"{base_name}={base_df[col].dtype}, "
                    f"{name}={df[col].dtype}"
                )

    return pd.concat(dfs, ignore_index=True)
