"""
Formulas de calculos trabalhistas brasileiros para contrato intermitente.
Baseado na CLT e tabelas INSS 2025.
"""


# Tabela INSS 2026 - aliquotas progressivas (Portaria MPS/MF No 13/2026)
INSS_BRACKETS_2025 = [
    (1621.00, 0.075),    # Ate R$ 1.621,00 -> 7,5%
    (2902.84, 0.09),     # De R$ 1.621,01 ate R$ 2.902,84 -> 9%
    (4354.27, 0.12),     # De R$ 2.902,85 ate R$ 4.354,27 -> 12%
    (8475.55, 0.14),     # De R$ 4.354,28 ate R$ 8.475,55 -> 14%
]

FGTS_RATE = 0.08  # 8%


def calculate_repouso_noturno(ad_noturno: float) -> float:
    """
    Calcula Repouso Remunerado sobre Adicional Noturno.
    Formula: Adicional Noturno / 6
    """
    return ad_noturno / 6.0 if ad_noturno > 0 else 0.0


def calculate_ferias_intermitente(salario_base: float, ad_noturno: float,
                                  dsr: float, repouso: float) -> float:
    """
    Calcula Ferias + 1/3 para contrato intermitente.
    Formula: (Salario + Ad.Noturno + DSR + Repouso) / 12 * (4/3)
    O 4/3 inclui o terco constitucional (1 + 1/3 = 4/3).
    """
    base = salario_base + ad_noturno + dsr + repouso
    return (base / 12.0) * (4.0 / 3.0)


def calculate_decimo_terceiro_intermitente(salario_base: float, ad_noturno: float,
                                           dsr: float, repouso: float) -> float:
    """
    Calcula 13o Salario para contrato intermitente.
    Formula: (Salario + Ad.Noturno + DSR + Repouso) / 12
    """
    base = salario_base + ad_noturno + dsr + repouso
    return base / 12.0


def calculate_inss(base_calculo: float) -> float:
    """
    Calcula INSS com aliquotas progressivas (tabela 2025).
    Cada faixa aplica apenas sobre o excedente da faixa anterior.
    """
    if base_calculo <= 0:
        return 0.0

    inss = 0.0
    prev_limit = 0.0

    for limit, rate in INSS_BRACKETS_2025:
        if base_calculo <= prev_limit:
            break
        taxable = min(base_calculo, limit) - prev_limit
        inss += taxable * rate
        prev_limit = limit

    return round(inss, 2)


def calculate_fgts(base_calculo: float) -> float:
    """Calcula FGTS: 8% sobre a base de calculo."""
    return round(base_calculo * FGTS_RATE, 2) if base_calculo > 0 else 0.0


def enrich_excel_data(excel: dict) -> dict:
    """
    Enriquece dados do Excel com calculos trabalhistas derivados.
    Adiciona campos _calc_* ao dicionario do funcionario.
    """
    sal = excel.get('total_salario_base', 0)
    ad_not = excel.get('total_ad_noturno', 0)
    dsr = excel.get('total_dsr', 0)

    # Repouso = Ad.Noturno / 6
    calc_repouso = calculate_repouso_noturno(ad_not)
    excel['_calc_repouso'] = round(calc_repouso, 2)

    # Ferias intermitente
    calc_ferias = calculate_ferias_intermitente(sal, ad_not, dsr, calc_repouso)
    excel['_calc_ferias'] = round(calc_ferias, 2)

    # 13o salario intermitente
    calc_decimo = calculate_decimo_terceiro_intermitente(sal, ad_not, dsr, calc_repouso)
    excel['_calc_decimo'] = round(calc_decimo, 2)

    # Base de calculo INSS folha = sal + ad_not + dsr + repouso + ferias (sem decimo)
    # O INSS sobre o 13o eh calculado separadamente (INSS 13o)
    base_inss_folha = sal + ad_not + dsr + calc_repouso + calc_ferias
    excel['_calc_inss_folha'] = calculate_inss(base_inss_folha)

    # INSS 13o = INSS sobre o valor do 13o
    excel['_calc_inss_13'] = calculate_inss(calc_decimo)

    # FGTS
    base_fgts = sal + ad_not + dsr + calc_repouso + calc_ferias + calc_decimo
    excel['_calc_fgts'] = calculate_fgts(base_fgts)

    return excel
