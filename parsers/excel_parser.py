import datetime
import io
import pandas as pd
from utils.formatting import parse_time_to_hours, parse_br_number


def parse_folha_de_ponto(file_bytes) -> dict:
    """
    Faz parse da folha de ponto Excel.
    Retorna dict com chave = nome do funcionario (original do Excel),
    valor = dict com totais agregados e lista de turnos.
    """
    if isinstance(file_bytes, bytes):
        file_bytes = io.BytesIO(file_bytes)
    df = pd.read_excel(file_bytes, sheet_name=0, header=None)

    # Auto-detectar colunas pelo cabecalho
    header_row, col_map = _detect_columns(df)

    employees = {}

    for idx in range(header_row + 1, len(df)):
        row = df.iloc[idx]
        nome = row.iloc[col_map['nome']]

        if not isinstance(nome, str) or not nome.strip():
            continue

        nome = nome.strip()

        # Extrair dados do turno
        shift = _parse_shift_row(row, col_map)
        if shift is None:
            continue

        if nome not in employees:
            employees[nome] = {
                'nome': nome,
                'salario_hora': shift['salario_hora'],
                'total_horas': 0.0,
                'total_noturno_horas': 0.0,
                'total_salario_base': 0.0,
                'total_ad_noturno': 0.0,
                'total_dsr': 0.0,
                'total_ajuda_custo': 0.0,
                'total_a_pagar': 0.0,
                'num_turnos': 0,
                'turnos': [],
            }

        emp = employees[nome]
        emp['total_horas'] += shift['horas_trabalhadas']
        emp['total_noturno_horas'] += shift['noturno_horas']
        emp['total_salario_base'] += shift['salario']
        emp['total_ad_noturno'] += shift['ad_noturno']
        emp['total_dsr'] += shift['dsr']
        emp['total_ajuda_custo'] += shift['ajuda_custo']
        emp['total_a_pagar'] += shift['total_a_pagar']
        emp['num_turnos'] += 1
        emp['turnos'].append(shift)

        # Atualiza salario_hora (pega o mais recente nao-zero)
        if shift['salario_hora'] > 0:
            emp['salario_hora'] = shift['salario_hora']

    return employees


def _detect_columns(df) -> tuple:
    """
    Auto-detecta colunas pelo conteudo do cabecalho.
    Retorna (header_row, col_map) onde col_map eh dict com indices das colunas.
    """
    # Keywords para cada campo (case-insensitive)
    COLUMN_KEYWORDS = {
        'evento': ['evento', 'local', 'unidade'],
        'data': ['^data$'],
        'nome': ['nome', 'funcionario', 'colaborador'],
        'horario_inicial': ['hor.*ini', 'inicio', 'entrada'],
        'horario_final': ['hor.*fin', 'hor.*fim', 'saida', 'termino'],
        'salario_hora': ['sal.*hora', 'valor.*hora', 'vl.*hora'],
        'horas_time': ['horas trab', 'horas.*trabalhadas$', 'ht$', 'total.*horas'],
        'noturno_time': ['^adicional noturno$', '^noturno$', 'adic.*not$'],
        'horas_num': ['horas.*trab.*num', 'qt.*horas'],
        'noturno_num': ['noturno.*num', 'adicional.*noturno.*num', 'qt.*not'],
        'salario': ['^sal.rio$', '^salario$', 'vl.*sal'],
        'ad_noturno': ['ad.*not.*20', 'adic.*not.*r\\$', 'vl.*not'],
        'dsr': ['^dsr', 'descanso'],
        'ajuda_custo': ['ajuda.*custo', 'aux.*transp'],
        'total_a_pagar': ['total.*pagar', 'total.*geral'],
    }

    # Indices padrao (fallback)
    DEFAULT_MAP = {
        'evento': 0, 'data': 1, 'nome': 2,
        'horario_inicial': 4, 'horario_final': 5,
        'salario_hora': 7,
        'horas_time': 12, 'noturno_time': 13,
        'horas_num': 14, 'noturno_num': 15,
        'salario': 16, 'ad_noturno': 18, 'dsr': 19,
        'ajuda_custo': 27, 'total_a_pagar': 30,
    }

    # Procurar header nas primeiras 10 linhas
    header_row = 2
    for i in range(min(10, len(df))):
        row_vals = [str(v).lower().strip() if isinstance(v, str) else '' for v in df.iloc[i]]
        # Verificar se tem pelo menos 'nome' nesta linha
        for j, val in enumerate(row_vals):
            if val and any(kw in val for kw in ['nome', 'funcionario', 'colaborador']):
                header_row = i
                break
        else:
            continue
        break

    # Tentar detectar colunas pelo header
    col_map = dict(DEFAULT_MAP)
    # Normalizar headers: lowercase, strip, newlines -> espaco
    header_vals = []
    for v in df.iloc[header_row]:
        if isinstance(v, str):
            header_vals.append(v.lower().strip().replace('\n', ' ').replace('\r', ' '))
        else:
            header_vals.append('')

    import re as _re
    for field_name, keywords in COLUMN_KEYWORDS.items():
        found = False
        for j, hval in enumerate(header_vals):
            if not hval:
                continue
            for kw in keywords:
                if _re.search(kw, hval, _re.IGNORECASE):
                    col_map[field_name] = j
                    found = True
                    break
            if found:
                break  # Usar primeira coluna que casar para este campo

    return header_row, col_map


def _parse_shift_row(row, col_map: dict) -> dict:
    """Faz parse de uma linha individual de turno usando col_map."""
    max_col = len(row)

    def _get(field, default=None):
        """Acessa coluna de forma segura, retornando default se fora do range."""
        idx = col_map.get(field)
        if idx is None or idx >= max_col:
            return default
        return row.iloc[idx]

    try:
        horario_ini = _parse_datetime(_get('horario_inicial'))
        horario_fim = _parse_datetime(_get('horario_final'))

        # Combinar horario time-only (ano 1900) com a data real do turno
        if horario_ini and horario_ini.year == 1900 or horario_fim and horario_fim.year == 1900:
            data_real = _parse_date_obj(_get('data'))
            if data_real:
                if horario_ini and horario_ini.year == 1900:
                    horario_ini = horario_ini.replace(year=data_real.year, month=data_real.month, day=data_real.day)
                if horario_fim and horario_fim.year == 1900:
                    horario_fim = horario_fim.replace(year=data_real.year, month=data_real.month, day=data_real.day)
                    if horario_ini and horario_fim < horario_ini:
                        horario_fim += datetime.timedelta(days=1)

        if horario_ini is None and horario_fim is None:
            return None

        salario_hora = _safe_float(_get('salario_hora', 0))

        horas_trab = parse_time_to_hours(_get('horas_time', 0))

        noturno_raw = _get('noturno_time')
        noturno_horas = 0.0
        if noturno_raw is not None and not _is_nan(noturno_raw):
            noturno_horas = parse_time_to_hours(noturno_raw)

        horas_num_str = _get('horas_num')
        if isinstance(horas_num_str, str):
            horas_num = parse_br_number(horas_num_str)
            if horas_num > 0:
                horas_trab = horas_num

        noturno_num_str = _get('noturno_num')
        if isinstance(noturno_num_str, str):
            noturno_num = parse_br_number(noturno_num_str)
            if noturno_num > 0:
                noturno_horas = noturno_num

        salario = _safe_float(_get('salario', 0))
        ad_noturno = _safe_float(_get('ad_noturno', 0))
        dsr = _safe_float(_get('dsr', 0))
        ajuda_custo = _safe_float(_get('ajuda_custo', 0))
        total_a_pagar = _safe_float(_get('total_a_pagar', 0))

        evento_raw = _get('evento', '')
        evento = str(evento_raw) if evento_raw is not None else ''
        data = _parse_date(_get('data'))

        return {
            'evento': evento,
            'data': data,
            'horario_inicial': horario_ini,
            'horario_final': horario_fim,
            'horas_trabalhadas': horas_trab,
            'noturno_horas': noturno_horas,
            'salario_hora': salario_hora,
            'salario': salario,
            'ad_noturno': ad_noturno,
            'dsr': dsr,
            'ajuda_custo': ajuda_custo,
            'total_a_pagar': total_a_pagar,
        }
    except Exception:
        return None


def _safe_float(val) -> float:
    """Converte valor para float de forma segura."""
    if val is None or _is_nan(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(',', '.'))
    except (ValueError, TypeError):
        return 0.0


def _is_nan(val) -> bool:
    """Verifica se valor e NaN."""
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(val, str) and val.lower() in ('nan', 'none', ''):
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    return False


def _parse_datetime(val):
    """Converte valor para datetime. Aceita datetime, time, e strings com ou sem data."""
    if val is None or _is_nan(val):
        return None
    if isinstance(val, datetime.datetime):
        return val
    if isinstance(val, datetime.time):
        return datetime.datetime.combine(datetime.date(1900, 1, 1), val)
    if isinstance(val, str):
        s = val.strip()
        for fmt in ('%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y', '%H:%M:%S', '%H:%M'):
            try:
                return datetime.datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def _parse_date_obj(val):
    """Converte valor para datetime.date object."""
    if val is None or _is_nan(val):
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        s = str(val).strip()
        for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _parse_date(val):
    """Converte valor para date string."""
    if val is None or _is_nan(val):
        return ''
    if isinstance(val, datetime.datetime):
        return val.strftime('%d/%m/%Y')
    if isinstance(val, datetime.date):
        return val.strftime('%d/%m/%Y')
    return str(val).strip()
