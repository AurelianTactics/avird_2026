'''
Builds reusable context files for AI/LLM-aided EDA work.

Outputs into eda/context/:
  * columns.txt                - full column list (one per line)
  * column_dtypes.csv          - column, dtype, n_unique, n_missing
  * value_counts/<col>.csv     - value counts for selected columns of interest
  * data_dictionary.md         - parsed text from the SGO PDF (markdown-ish)
  * data_dictionary.csv        - element, definition rows extracted from the PDF

Run from the repo root:
    python eda/context/_build_context.py
'''
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

REPO_ROOT = Path(__file__).resolve().parents[2]
EDA_DIR = REPO_ROOT / 'eda'
CONTEXT_DIR = EDA_DIR / 'context'
DATA_DIR = REPO_ROOT / 'data' / 'nhtsa'
PDF_PATH = DATA_DIR / 'SGO-2021-01_Data_Element_Definitions.pdf'

# Columns the LLM-friendly value_counts dump should cover.  Add as needed.
VALUE_COUNT_COLS = [
    'Reporting Entity',
    'Operating Entity',
    'Make',
    'Model',
    'State',
    'City',
    'State or Local Permit',
    'Investigating Agency',
    'Roadway Type',
    'Crash With',
    'Highest Injury Severity Alleged',
    'CP Pre-Crash Movement',
    'SV Pre-Crash Movement',
    'Driver / Operator Type',
    'Automation System Engaged?',
    'Engagement Status',
    'Within ODD?',
    'Any Air Bags Deployed?',
    'Was Any Vehicle Towed?',
    'Were All Passengers Belted?',
]


def load_df():
    sys.path.insert(0, str(EDA_DIR))
    from eda_utils_sgo import load_and_concat_csvs
    paths = sorted(DATA_DIR.glob('SGO-2021-01_Incident_Reports_ADS*.csv'))
    return load_and_concat_csvs([str(p) for p in paths])


def write_columns(df):
    (CONTEXT_DIR / 'columns.txt').write_text(
        '\n'.join(df.columns) + '\n', encoding='utf-8'
    )
    rows = []
    for c in df.columns:
        rows.append({
            'column': c,
            'dtype': str(df[c].dtype),
            'n_unique': int(df[c].nunique(dropna=False)),
            'n_missing': int(df[c].isna().sum()),
        })
    pd.DataFrame(rows).to_csv(CONTEXT_DIR / 'column_dtypes.csv', index=False)


def write_value_counts(df, top_k=200):
    out_dir = CONTEXT_DIR / 'value_counts'
    out_dir.mkdir(exist_ok=True)
    for col in VALUE_COUNT_COLS:
        if col not in df.columns:
            continue
        s = df[col].value_counts(dropna=False).head(top_k)
        safe = re.sub(r'[^A-Za-z0-9]+', '_', col).strip('_')
        out = pd.DataFrame({col: s.index.astype(str), 'count': s.values})
        out.to_csv(out_dir / f'{safe}.csv', index=False)


# ---------- PDF parsing ---------------------------------------------------
def extract_pdf_text(pdf_path=PDF_PATH):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ''
            pages.append(t)
    return pages


def write_data_dictionary_md(pages):
    out = ['# SGO 2021-01 Data Element Definitions', '']
    for i, t in enumerate(pages, start=1):
        out.append(f'## Page {i}')
        out.append('')
        out.append(t.strip())
        out.append('')
    (CONTEXT_DIR / 'data_dictionary.md').write_text(
        '\n'.join(out), encoding='utf-8'
    )


# Heuristic: PDF rows look like "<Element Name>  <Definition...>" within a
# table.  pdfplumber.extract_tables() works better than line regex here.
def write_data_dictionary_csv(pdf_path=PDF_PATH):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables() or []:
                for row in table:
                    cleaned = [
                        (c or '').replace('\n', ' ').strip() for c in row
                    ]
                    if not any(cleaned):
                        continue
                    rows.append({'page': page_idx, 'cells': cleaned})
    flat = []
    for r in rows:
        cells = r['cells']
        if len(cells) >= 2 and cells[0] and cells[1]:
            flat.append({
                'page': r['page'],
                'element': cells[0],
                'definition': ' | '.join(c for c in cells[1:] if c),
            })
    if flat:
        pd.DataFrame(flat).to_csv(
            CONTEXT_DIR / 'data_dictionary.csv', index=False
        )


def main():
    CONTEXT_DIR.mkdir(exist_ok=True)
    df = load_df()
    write_columns(df)
    write_value_counts(df)
    pages = extract_pdf_text()
    write_data_dictionary_md(pages)
    write_data_dictionary_csv()
    print(f'Wrote context to {CONTEXT_DIR}')


if __name__ == '__main__':
    main()
