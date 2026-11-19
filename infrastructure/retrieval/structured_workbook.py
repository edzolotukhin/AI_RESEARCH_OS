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
        tables.extend(_hierarchical_year_tables(sheet, index=index, rows=rows))
    return tables


def _hierarchical_year_tables(sheet, *, index, rows):
    """Project conservative multi-level year tables into explicit rows.

    Official workbooks commonly use merged multi-level headers and append a
    one-digit footnote marker to the year.  A projection is emitted only for a
    contiguous year sequence with unique resolved metric headers.  Unit and
    territorial footnote cells remain literal, coordinate-addressable support.
    """
    candidates=[]
    for offset,row in enumerate(rows):
        parsed=_year_and_marker(row[0].value if row else None)
        if parsed is not None:
            candidates.append((offset,parsed))
    groups=[]
    current=[]
    for item in candidates:
        if current and (item[0] != current[-1][0]+1 or item[1][0] != current[-1][1][0]+1):
            if len(current)>=2:
                groups.append(current)
            current=[]
        current.append(item)
    if len(current)>=2:
        groups.append(current)

    projected=[]
    for group in groups:
        # Exact four-digit tables are already handled by the legacy explicit
        # header path when they have a conventional Year header.
        if all(not marker for _,(_,marker) in group):
            continue
        start=group[0][0]
        header_rows=_header_rows(rows,start)
        if not header_rows:
            continue
        max_col=max((
            cell.column for offset,_ in group for cell in rows[offset]
            if cell.value is not None and str(cell.value).strip()
        ),default=0)
        paths=[_header_path(sheet,header_rows,col) for col in range(1,max_col+1)]
        common=set(paths[1]) if len(paths)>1 else set()
        for path in paths[2:]:
            common.intersection_update(path)
        headers=[]
        for col,path in enumerate(paths,start=1):
            if col==1:
                headers.append("Year")
            else:
                headers.append(" / ".join(value for value in path if value not in common))
        if any(not value for value in headers) or len(set(value.casefold() for value in headers)) != len(headers):
            continue
        unit_support=_unit_support(sheet,header_rows)
        footnotes=_footnotes(rows,group[-1][0]+1)
        header_cells=[_header_coordinate(sheet,header_rows,col) for col in range(1,max_col+1)]
        first_row=rows[header_rows[0]][0].row
        last_row=rows[group[-1][0]][0].row
        table_range=f"A{first_row}:{get_column_letter(max_col)}{last_row}"
        header_checksum=sha256(json.dumps((header_cells,headers),ensure_ascii=False).encode()).hexdigest()
        for offset,(year,marker) in group:
            row=rows[offset]
            cells=[]
            for col,(header,cell) in enumerate(zip(headers,row),start=1):
                value=year if col==1 else cell.value
                numeric=None
                if not isinstance(value,bool) and value is not None and cell.data_type!="f":
                    try:
                        number=Decimal(str(value))
                        if number.is_finite():
                            numeric=str(number)
                    except InvalidOperation:
                        pass
                cells.append({"column":col,"cell":cell.coordinate,"header":header,
                    "value":str(value) if value is not None else "","numeric_value":numeric,
                    "formula":cell.data_type=="f"})
            support=[]
            if unit_support is not None:
                coordinate,value=unit_support
                support.append({"column":max_col+1,"cell":coordinate,"header":"Unit",
                    "value":value,"numeric_value":None,"formula":False})
            geography=footnotes.get(marker) if marker else None
            if geography is not None:
                coordinate,value=geography
                support.append({"column":max_col+2,"cell":coordinate,"header":"Geography",
                    "value":value,"numeric_value":None,"formula":False})
            cells.extend(support)
            excerpt=f'Sheet="{sheet.title}" | Table="{table_range}" | Row={row[0].row} | '+" | ".join(
                f'{cell["header"]}={cell["value"]}' for cell in cells if cell["value"])
            projected.append({"sheet":sheet.title,"sheet_index":index,"table_range":table_range,
                "header_cells":header_cells,"header_values":headers,"header_checksum":header_checksum,
                "row":row[0].row,"cells":cells,"excerpt":excerpt,"ambiguous_headers":False})
    return projected


def _year_and_marker(value):
    if isinstance(value,bool) or value is None:
        return None
    text=str(value).strip()
    match=re.fullmatch(r"((?:19|20)\d{2})(\d?)",text)
    if not match:
        return None
    return int(match.group(1)),match.group(2)


def _header_rows(rows,start):
    result=[]
    for offset in range(max(0,start-8),start):
        if any(cell.value is not None and str(cell.value).strip() for cell in rows[offset]):
            result.append(offset)
    return result


def _merged_value(sheet,row,col):
    cell=sheet.cell(row=row,column=col)
    if cell.value is not None:
        return cell.value,cell.coordinate
    for area in sheet.merged_cells.ranges:
        if area.min_row<=row<=area.max_row and area.min_col<=col<=area.max_col:
            anchor=sheet.cell(row=area.min_row,column=area.min_col)
            return anchor.value,anchor.coordinate
    return None,cell.coordinate


def _header_path(sheet,header_rows,col):
    values=[]
    for offset in header_rows:
        value,_=_merged_value(sheet,offset+1,col)
        text=str(value).strip() if value is not None else ""
        if text and text not in values:
            values.append(text)
    return values


def _header_coordinate(sheet,header_rows,col):
    for offset in reversed(header_rows):
        value,coordinate=_merged_value(sheet,offset+1,col)
        if value is not None and str(value).strip():
            return coordinate
    return sheet.cell(row=header_rows[-1]+1,column=col).coordinate


def _unit_support(sheet,header_rows):
    for offset in header_rows:
        for cell in sheet[offset+1]:
            value=str(cell.value or "").strip()
            folded=value.casefold()
            if cell.data_type != "f" and value and ("тис. осіб" in folded or "thsd." in folded):
                return cell.coordinate,value
    return None


def _footnotes(rows,start):
    found={}
    for row in rows[start:start+8]:
        for cell in row:
            value=str(cell.value or "").strip()
            match=re.match(r"^(\d)\s+(.+)$",value,re.S)
            if cell.data_type != "f" and match and ("територ" in value.casefold() or "territor" in value.casefold()):
                marker=match.group(1)
                # Bilingual official footnotes repeat the marker before the
                # English clause.  Keep one literal clause as the bounded
                # authority value while the raw workbook checksum and cell
                # coordinate pin the complete source cell.
                separator=f"/{marker} "
                authority=value.split(separator,1)[1].strip() if separator in value else value
                found[marker]=(cell.coordinate,authority)
    return found
