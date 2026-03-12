"""
Parser para o Relatorio de Medicao por Cliente extraido do sistema interno.
Extrai turnos individuais com horarios de entrada/saida.
"""
import pandas as pd
import datetime
import io
import re


def parse_medicao(file_bytes) -> list:
    """
    Faz parse do Relatorio de Medicao por Cliente.
    Retorna lista de dicts, um por turno.
    """
    if isinstance(file_bytes, bytes):
        file_bytes = io.BytesIO(file_bytes)
    df = pd.read_excel(
        file_bytes,
        sheet_name=0,
        header=None,
        engine='openpyxl',
    )

    # Detectar linha de header procurando "Nome" na coluna
    header_row = _find_header_row(df)
    if header_row is None:
        raise ValueError("Nao foi possivel encontrar o header da planilha de medicao")

    # Reconfigurar com header correto
    df.columns = df.iloc[header_row].astype(str).str.strip()
    df = df.iloc[header_row + 1:].reset_index(drop=True)

    # Remover linhas totalmente vazias
    df = df.dropna(how='all')

    # Mapear colunas (flexivel para variacoes de nome)
    col_map = _map_columns(df.columns.tolist())

    turnos = []
    for _, row in df.iterrows():
        nome = _safe_str(row.get(col_map.get('nome', ''), ''))
        if not nome or nome.lower() in ('nan', 'none', ''):
            continue

        turno = {
            'nome': nome.strip(),
            'data': _parse_date(row.get(col_map.get('data', ''), None)),
            'data_final': _parse_date(row.get(col_map.get('data_final', ''), None)),
            'setor': _safe_str(row.get(col_map.get('setor', ''), '')),
            'funcao': _safe_str(row.get(col_map.get('funcao', ''), '')),
            'horario_inicial': _parse_time(row.get(col_map.get('horario_inicial', ''), None)),
            'horario_final': _parse_time(row.get(col_map.get('horario_final', ''), None)),
            'horas_totais': _parse_hours(row.get(col_map.get('horas_totais', ''), None)),
            'descritivo': _safe_str(row.get(col_map.get('descritivo', ''), '')),
            'dia_semana': _safe_str(row.get(col_map.get('dia_semana', ''), '')),
        }
        turnos.append(turno)

    return turnos


def _find_header_row(df, max_rows=10):
    """Encontra a linha que contem os headers procurando por palavras-chave."""
    keywords = ['nome', 'data', 'hor.rio']
    for i in range(min(max_rows, len(df))):
        row_text = ' '.join(str(v).lower().strip() for v in df.iloc[i].values if pd.notna(v))
        matches = sum(1 for kw in keywords if kw in row_text)
        if matches >= 2:
            return i
    return None


def _map_columns(columns):
    """Mapeia nomes de colunas para campos padronizados."""
    col_map = {}
    patterns = {
        'nome': [r'nome'],
        'data': [r'^data$', r'data\s*inicial'],
        'data_final': [r'data\s*final'],
        'setor': [r'setor', r'local', r'evento'],
        'funcao': [r'fun[cç][aã]o', r'cargo'],
        'horario_inicial': [r'hor.rio\s*inicial', r'entrada', r'in[ií]cio'],
        'horario_final': [r'hor.rio\s*final', r'sa[ií]da', r'fim'],
        'horas_totais': [r'horas?\s*tota', r'total.*horas'],
        'descritivo': [r'descritivo', r'descri[cç]'],
        'dia_semana': [r'dia.*semana'],
    }

    for col in columns:
        col_lower = str(col).lower().strip()
        for field, pats in patterns.items():
            if field not in col_map:
                for pat in pats:
                    if re.search(pat, col_lower):
                        col_map[field] = col
                        break

    return col_map


def _safe_str(val):
    """Converte valor para string de forma segura."""
    if pd.isna(val):
        return ''
    return str(val).strip()


def _parse_date(val):
    """Converte valor para datetime.date."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        s = str(val).strip()
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _parse_time(val):
    """Converte valor para datetime.time."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime.time):
        return val
    if isinstance(val, datetime.datetime):
        return val.time()
    try:
        s = str(val).strip()
        for fmt in ('%H:%M:%S', '%H:%M'):
            try:
                return datetime.datetime.strptime(s, fmt).time()
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _parse_hours(val):
    """Converte valor de horas para float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, datetime.time):
        return val.hour + val.minute / 60.0
    if isinstance(val, datetime.timedelta):
        return val.total_seconds() / 3600.0
    try:
        s = str(val).strip()
        if ':' in s:
            parts = s.split(':')
            return int(parts[0]) + int(parts[1]) / 60.0
        return float(s)
    except Exception:
        return 0.0
