"""
Motor de calculo para transformar Relatorio de Medicao em Folha de Pagamento.
Aplica todas as provisoes, encargos e beneficios conforme CLT.
"""
import datetime
import pandas as pd


# Tabela INSS 2026 - aliquotas progressivas (Portaria MPS/MF No 13/2026)
INSS_BRACKETS_2026 = [
    (1621.00, 0.075),    # Ate R$ 1.621,00 -> 7,5%
    (2902.84, 0.09),     # De R$ 1.621,01 ate R$ 2.902,84 -> 9%
    (4354.27, 0.12),     # De R$ 2.902,85 ate R$ 4.354,27 -> 12%
    (8475.55, 0.14),     # De R$ 4.354,28 ate R$ 8.475,55 -> 14%
]

# Parametros default
DEFAULT_PARAMS = {
    'salario_base_mensal': 1621.00,
    'divisor_horas': 220,
    'dsr_fator': 1 / 6,
    'ferias_fator': 1 / 12,
    'ferias_adicional': 1 / 3,
    'decimo_fator': 1 / 12,
    'vt_desconto': 0.0,
    'ajuda_custo': 30.0,
}

# Fator hora ficta noturna: 60min / 52.5min = 8/7
HORA_FICTA_FATOR = 8.0 / 7.0

# Adicional noturno: 20%
ADICIONAL_NOTURNO_PCT = 0.20


# --- Regras de acrescimo de Ajuda de Custo (BH) ---
# Valores sao CUMULATIVOS: cada regra atendida soma +R$15,00

# Regra 1: Setores especificos
SETORES_ACRESCIMO = {
    'scp shop. monte carmo',
    'shopping ponteio',
    'aeroporto lagoa santa',
}

ACRESCIMO_LOCALIZACAO = 30.0
ACRESCIMO_NOTURNO = 15.0

# Regras especificas por funcionario (nome normalizado -> overrides)
REGRAS_FUNCIONARIO = {
    'jorge de sousa rocha': {
        'ajuda_custo': 40.10,
        'salario_hora': 8.41,
    },
}


def _normalize(s: str) -> str:
    """Remove acentos e normaliza para comparacao flexivel."""
    import unicodedata
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def calcular_acrescimo_ajuda_custo(setor: str, horario_final, horario_inicial, horas_totais: float) -> float:
    """
    Calcula acrescimo cumulativo de ajuda de custo conforme regras BH.
    Cada regra atendida soma +R$15,00 e sao cumulativas.

    Regra 1: Setor em SCP Shop. Monte Carmo, Shopping Ponteio ou Aeroporto Lagoa Santa
    Regra 2: Saida a partir das 23:00h (inclusive)
    Regra 3: Diaria de 12h com entrada 18:00 e saida 06:00
    Regra 4: Diaria de 12h com entrada 19:00 e saida 07:00

    Returns:
        Total de acrescimo (multiplo de R$15,00)
    """
    acrescimo = 0.0

    # Regra 1: setor especifico (+R$30)
    setor_norm = _normalize(setor) if setor else ''
    for local in SETORES_ACRESCIMO:
        if setor_norm == local or local in setor_norm or setor_norm in local:
            acrescimo += ACRESCIMO_LOCALIZACAO
            break

    # Extrair hora/minuto dos horarios
    hi_hour, hi_min = _extract_hm(horario_inicial)
    hf_hour, hf_min = _extract_hm(horario_final)

    # Regras 2, 3 e 4 sao mutuamente exclusivas: apenas +R$15 se qualquer uma se aplica
    horas_int = round(horas_totais) if horas_totais else 0
    regra_noturna = False

    # Regra 3: 12h, entrada 18:00, saida 06:00
    if horas_int == 12 and hi_hour == 18 and hi_min == 0 and hf_hour == 6 and hf_min == 0:
        regra_noturna = True

    # Regra 4: 12h, entrada 19:00, saida 07:00
    if not regra_noturna and horas_int == 12 and hi_hour == 19 and hi_min == 0 and hf_hour == 7 and hf_min == 0:
        regra_noturna = True

    # Regra 2: saida a partir das 23:00h (inclusive) ou turno cruza meia-noite
    if not regra_noturna and hf_hour is not None and hi_hour is not None:
        cruza_meia_noite = hf_hour < hi_hour
        if hf_hour >= 23 or cruza_meia_noite:
            regra_noturna = True

    if regra_noturna:
        acrescimo += ACRESCIMO_NOTURNO

    return acrescimo


def _extract_hm(horario) -> tuple:
    """Extrai (hora, minuto) de um datetime.time, datetime.datetime ou None."""
    if horario is None:
        return (None, None)
    if isinstance(horario, datetime.time):
        return (horario.hour, horario.minute)
    if isinstance(horario, datetime.datetime):
        return (horario.hour, horario.minute)
    return (None, None)


def calculate_inss_2026(base_calculo: float) -> float:
    """
    Calcula INSS com aliquotas progressivas (tabela 2026).
    Cada faixa aplica apenas sobre a parcela naquele intervalo.
    Trunca em 2 casas decimais.
    """
    if base_calculo <= 0:
        return 0.0

    inss = 0.0
    prev_limit = 0.0

    for limit, rate in INSS_BRACKETS_2026:
        if base_calculo <= prev_limit:
            break
        taxable = min(base_calculo, limit) - prev_limit
        inss += taxable * rate
        prev_limit = limit

    # Truncar em 2 casas (pratica de sistemas de folha)
    return int(inss * 100) / 100.0


def _calc_night_clock_hours(start_dt: datetime.datetime, end_dt: datetime.datetime) -> float:
    """
    Calcula horas relogio dentro da janela noturna (22:00-05:00).
    Correto para turnos que cruzam meia-noite.
    Gera todas as janelas noturnas que podem sobrepor o turno.
    """
    if start_dt >= end_dt:
        return 0.0

    total = 0.0

    # Gerar janelas noturnas que podem sobrepor o turno
    # Comecar pelo dia anterior ao inicio (caso turno comece entre 00-05h)
    base_day = start_dt.date() - datetime.timedelta(days=1)
    end_day = end_dt.date() + datetime.timedelta(days=1)

    current_day = base_day
    while current_day <= end_day:
        # Janela noturna: 22:00 do dia ate 05:00 do dia seguinte
        night_start = datetime.datetime.combine(current_day, datetime.time(22, 0))
        night_end = datetime.datetime.combine(current_day + datetime.timedelta(days=1), datetime.time(5, 0))

        # Sobreposicao
        overlap_start = max(start_dt, night_start)
        overlap_end = min(end_dt, night_end)

        if overlap_start < overlap_end:
            total += (overlap_end - overlap_start).total_seconds() / 3600.0

        current_day += datetime.timedelta(days=1)

    return total


def calculate_night_hours_ficta(horario_inicial, horario_final, data_inicial=None, data_final=None) -> float:
    """
    Calcula horas noturnas com hora ficta (CLT Art. 73).
    - Periodo noturno: 22h00 as 05h00
    - Hora ficta: 52min30s = 1h noturna (fator 8/7)

    Retorna horas noturnas fictas (float).
    """
    if horario_inicial is None or horario_final is None:
        return 0.0

    # Montar datetime para calculo
    if data_inicial is None:
        data_inicial = datetime.date(2026, 1, 1)
    if data_final is None:
        data_final = data_inicial

    start_dt = datetime.datetime.combine(data_inicial, horario_inicial)
    end_dt = datetime.datetime.combine(data_final, horario_final)

    # Se end <= start, turno cruza meia-noite
    if end_dt <= start_dt:
        end_dt += datetime.timedelta(days=1)

    # Calcular horas relogio no periodo noturno (sem dupla contagem)
    night_clock_hours = _calc_night_clock_hours(start_dt, end_dt)

    # Converter para horas fictas
    night_ficta_hours = night_clock_hours * HORA_FICTA_FATOR

    return round(night_ficta_hours, 4)


def build_payroll(turnos: list, params: dict = None, aplicar_regras_bh: bool = False) -> pd.DataFrame:
    """
    Transforma lista de turnos em DataFrame com todos os calculos de folha.

    Args:
        turnos: Lista de dicts do parser de medicao
        params: Parametros configuraveis (usa DEFAULT_PARAMS se None)
        aplicar_regras_bh: Se True, aplica regras cumulativas de acrescimo BH na ajuda de custo

    Returns:
        DataFrame com uma linha por turno e todas as colunas calculadas
    """
    if params is None:
        params = DEFAULT_PARAMS.copy()
    else:
        # Preencher com defaults para campos nao informados
        merged = DEFAULT_PARAMS.copy()
        merged.update(params)
        params = merged

    salario_hora = params['salario_base_mensal'] / params['divisor_horas']

    rows = []
    for turno in turnos:
        row = _calculate_turno(turno, salario_hora, params, aplicar_regras_bh)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Calcular INSS progressivo por funcionario (somando turnos)
    df = _apply_inss_por_funcionario(df)

    # Recalcular salario liquido e total apos INSS
    df['sal_liquido'] = (
        df['salario'] + df['gratif_funcao'] + df['ad_noturno_valor'] +
        df['dsr'] + df['ferias'] + df['adic_ferias'] + df['decimo']
        - df['inss'] - df['inss_13'] - df['desc_vt']
    )
    df['total_pagar'] = df['sal_liquido'] + df['ajuda_custo'] + df['desc_adiantamento'] + df['sal_familia']

    # Arredondar valores monetarios
    money_cols = [
        'salario_hora', 'salario', 'gratif_funcao', 'ad_noturno_valor',
        'dsr', 'ferias', 'adic_ferias', 'decimo', 'inss', 'inss_13',
        'desc_vt', 'sal_liquido', 'ajuda_custo', 'total_pagar',
    ]
    for col in money_cols:
        if col in df.columns:
            df[col] = df[col].round(2)

    return df


def _calculate_turno(turno: dict, salario_hora: float, params: dict, aplicar_regras_bh: bool = False) -> dict:
    """Calcula todos os campos para um turno individual."""
    hi = turno.get('horario_inicial')
    hf = turno.get('horario_final')
    data = turno.get('data')
    data_final = turno.get('data_final', data)

    # Verificar regras especificas por funcionario
    nome_norm = _normalize(turno.get('nome', ''))
    regra_func = REGRAS_FUNCIONARIO.get(nome_norm, {})
    if 'salario_hora' in regra_func:
        salario_hora = regra_func['salario_hora']

    # Horas trabalhadas
    horas_trabalhadas = _calc_horas_trabalhadas(hi, hf, data, data_final)

    # Horas noturnas fictas
    horas_noturnas = calculate_night_hours_ficta(hi, hf, data, data_final)

    # Intervalo (default 0 - nao vem no relatorio de medicao)
    intervalo = turno.get('intervalo', 0.0)
    horas_efetivas = max(horas_trabalhadas - intervalo, 0)

    # Gratificacao (default 0)
    gratif_valor = turno.get('gratificacao', 0.0)

    # Calculos monetarios
    salario = horas_efetivas * salario_hora
    gratif_funcao = horas_efetivas * gratif_valor if gratif_valor > 0 else 0.0
    ad_noturno_valor = horas_noturnas * salario_hora * ADICIONAL_NOTURNO_PCT

    base_dsr = salario + gratif_funcao + ad_noturno_valor
    dsr = base_dsr * params['dsr_fator']

    base_provisoes = salario + gratif_funcao + ad_noturno_valor + dsr
    ferias = base_provisoes * params['ferias_fator']
    adic_ferias = ferias * params['ferias_adicional']
    decimo = base_provisoes * params['decimo_fator']

    desc_vt = salario * params['vt_desconto']

    # INSS sera calculado depois (por funcionario), placeholder 0
    inss = 0.0
    inss_13 = 0.0

    sal_liquido = salario + gratif_funcao + ad_noturno_valor + dsr + ferias + adic_ferias + decimo - inss - inss_13 - desc_vt
    ajuda_custo = regra_func.get('ajuda_custo', params['ajuda_custo'])

    # Aplicar acrescimos cumulativos de ajuda de custo (regras BH)
    acrescimo_bh = 0.0
    if aplicar_regras_bh:
        acrescimo_bh = calcular_acrescimo_ajuda_custo(
            setor=turno.get('setor', ''),
            horario_final=hf,
            horario_inicial=hi,
            horas_totais=horas_trabalhadas,
        )
        ajuda_custo += acrescimo_bh

    total_pagar = sal_liquido + ajuda_custo

    return {
        'evento': turno.get('setor', ''),
        'data': data,
        'nome': turno.get('nome', ''),
        'funcao': turno.get('funcao', ''),
        'horario_inicial': hi,
        'horario_final': hf,
        'funcao_contrato': turno.get('funcao', ''),
        'salario_hora': round(salario_hora, 2),
        'salario_funcao': round(salario_hora, 2),
        'gratificacao': gratif_valor,
        'total_horas': round(horas_trabalhadas, 2),
        'intervalo': intervalo,
        'horas_trabalhadas': round(horas_efetivas, 2),
        'horas_noturnas': round(horas_noturnas, 2),
        'horas_trab_num': round(horas_efetivas, 2),
        'horas_not_num': round(horas_noturnas, 2),
        'salario': round(salario, 2),
        'gratif_funcao': round(gratif_funcao, 2),
        'ad_noturno_valor': round(ad_noturno_valor, 2),
        'dsr': round(dsr, 2),
        'ferias': round(ferias, 2),
        'adic_ferias': round(adic_ferias, 2),
        'decimo': round(decimo, 2),
        'inss': inss,
        'inss_13': inss_13,
        'desc_vt': round(desc_vt, 2),
        'sal_liquido': round(sal_liquido, 2),
        'ajuda_custo': ajuda_custo,
        'desc_adiantamento': 0.0,
        'sal_familia': 0.0,
        'total_pagar': round(total_pagar, 2),
        # Campos auxiliares para INSS por funcionario
        '_base_inss': round(salario + gratif_funcao + ad_noturno_valor + dsr + ferias + adic_ferias, 2),
        '_base_inss_13': round(decimo, 2),
    }


def _calc_horas_trabalhadas(hi, hf, data=None, data_final=None) -> float:
    """Calcula horas trabalhadas entre horario inicial e final."""
    if hi is None or hf is None:
        return 0.0

    if data is None:
        data = datetime.date(2026, 1, 1)
    if data_final is None:
        data_final = data

    start = datetime.datetime.combine(data, hi)
    end = datetime.datetime.combine(data_final, hf)

    if end <= start:
        end += datetime.timedelta(days=1)

    diff = (end - start).total_seconds() / 3600.0
    return max(diff, 0)


def _apply_inss_por_funcionario(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula INSS progressivo por funcionario, somando todas as bases
    de todos os turnos do periodo, e rateia proporcionalmente por turno.
    """
    if df.empty:
        return df

    for nome, group in df.groupby('nome'):
        idx = group.index

        # Base INSS total do funcionario (soma de todos os turnos)
        total_base_inss = group['_base_inss'].sum()
        total_base_inss_13 = group['_base_inss_13'].sum()

        # Calcular INSS total progressivo
        inss_total = calculate_inss_2026(total_base_inss)
        inss_13_total = calculate_inss_2026(total_base_inss_13)

        # Ratear proporcionalmente por turno
        if total_base_inss > 0:
            for i in idx:
                prop = df.at[i, '_base_inss'] / total_base_inss
                df.at[i, 'inss'] = round(inss_total * prop, 2)
        if total_base_inss_13 > 0:
            for i in idx:
                prop = df.at[i, '_base_inss_13'] / total_base_inss_13
                df.at[i, 'inss_13'] = round(inss_13_total * prop, 2)

    return df


def get_summary_by_employee(df: pd.DataFrame) -> pd.DataFrame:
    """Gera resumo agrupado por funcionario."""
    if df.empty:
        return pd.DataFrame()

    summary = df.groupby('nome').agg({
        'horas_trab_num': 'sum',
        'horas_not_num': 'sum',
        'salario': 'sum',
        'gratif_funcao': 'sum',
        'ad_noturno_valor': 'sum',
        'dsr': 'sum',
        'ferias': 'sum',
        'adic_ferias': 'sum',
        'decimo': 'sum',
        'inss': 'sum',
        'inss_13': 'sum',
        'desc_vt': 'sum',
        'sal_liquido': 'sum',
        'ajuda_custo': 'sum',
        'desc_adiantamento': 'sum',
        'sal_familia': 'sum',
        'total_pagar': 'sum',
        'data': 'count',
    }).rename(columns={'data': 'qtd_turnos'}).reset_index()

    summary = summary.round(2)
    return summary
