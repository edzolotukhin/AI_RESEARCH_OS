"""Conservative explicit-header tables; formulas and merged headers fail closed."""
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from openpyxl.utils import get_column_letter


def explicit_tables(workbook, bounds):
    tables=[]
    for index,sheet in enumerate(workbook.worksheets[:bounds.max_sheets]):
        if sheet.sheet_state != "visible":
            continue
        rows=list(sheet.iter_rows(max_row=min(sheet.max_row,bounds.max_rows_per_sheet),max_col=min(sheet.max_column,bounds.max_columns_per_sheet)))
        starts=[i for i,row in enumerate(rows) if sum(str(c.value or "").strip().casefold() in {"year","рік","год"} for c in row)==1]
        for position,start in enumerate(starts):
            headers=[str(c.value or "").strip() for c in rows[start]]
            end=starts[position+1] if position+1<len(starts) else len(rows)
            data=[]
            for row in rows[start+1:end]:
                if all(c.value is None for c in row):
                    break
                data.append(row)
            if not data:
                continue
            first,last=rows[start][0].row,data[-1][0].row
            table_range=f"A{first}:{get_column_letter(len(headers))}{last}"
            merged=any(r.min_row<=last and r.max_row>=first for r in sheet.merged_cells.ranges)
            # A preceding nonempty header level can qualify the metric (sex,
            # subgroup, unit, etc.). Until resolved explicitly, do not discard it.
            preceding_level=start>0 and any(c.value is not None for c in rows[start-1])
            ambiguous=merged or preceding_level or len([h for h in headers if h]) != len(set(h.casefold() for h in headers if h))
            header_cells=[c.coordinate for c in rows[start]]
            header_checksum=sha256(json.dumps((header_cells,headers),ensure_ascii=False).encode()).hexdigest()
            for row in data:
                cells=[]
                for header,cell in zip(headers,row):
                    value=cell.value
                    numeric=None
                    if not isinstance(value,bool) and value is not None and cell.data_type!="f":
                        try:
                            number=Decimal(str(value))
                            if number.is_finite():
                                numeric=str(number)
                        except InvalidOperation:
                            pass
                    cells.append({"column":cell.column,"cell":cell.coordinate,"header":header,
                        "value":str(value) if value is not None else "", "numeric_value":numeric,
                        "formula":cell.data_type=="f"})
                excerpt=f'Sheet="{sheet.title}" | Table="{table_range}" | Row={row[0].row} | '+" | ".join(f'{c["header"]}={c["value"]}' for c in cells if c["header"])
                tables.append({"sheet":sheet.title,"sheet_index":index,"table_range":table_range,
                    "header_cells":header_cells,"header_values":headers,"header_checksum":header_checksum,
                    "row":row[0].row,"cells":cells,"excerpt":excerpt,"ambiguous_headers":ambiguous})
    return tables
