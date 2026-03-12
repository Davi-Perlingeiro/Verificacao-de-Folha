"""
Modulo de feriados nacionais e estaduais (RJ).
Inclui feriados moveis calculados via algoritmo de Computus (Pascoa).
"""

import datetime
from functools import lru_cache


# Feriados nacionais fixos (mes, dia)
FERIADOS_NACIONAIS_FIXOS = [
    (1, 1, "Confraternizacao Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independencia do Brasil"),
    (10, 12, "Nossa Sra. Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamacao da Republica"),
    (12, 25, "Natal"),
]

# Feriados estaduais RJ fixos (mes, dia)
FERIADOS_RJ_FIXOS = [
    (4, 23, "Dia de Sao Jorge"),
    (11, 20, "Dia da Consciencia Negra"),
]


def _easter_date(year: int) -> datetime.date:
    """
    Calcula a data da Pascoa usando o algoritmo de Computus (Meeus/Jones/Butcher).
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)


@lru_cache(maxsize=10)
def get_all_holidays(year: int) -> dict:
    """
    Retorna dict[datetime.date] -> nome do feriado para o ano.
    Inclui feriados nacionais (fixos + moveis) e estaduais RJ.
    """
    holidays = {}

    # Fixos nacionais
    for month, day, name in FERIADOS_NACIONAIS_FIXOS:
        holidays[datetime.date(year, month, day)] = name

    # Fixos RJ
    for month, day, name in FERIADOS_RJ_FIXOS:
        holidays[datetime.date(year, month, day)] = name

    # Moveis (baseados na Pascoa)
    easter = _easter_date(year)

    # Carnaval: 47 dias antes da Pascoa (segunda e terca)
    carnaval_seg = easter - datetime.timedelta(days=48)
    carnaval_ter = easter - datetime.timedelta(days=47)
    holidays[carnaval_seg] = "Carnaval (Segunda)"
    holidays[carnaval_ter] = "Carnaval (Terca)"

    # Quarta-feira de Cinzas (ponto facultativo, mas relevante)
    cinzas = easter - datetime.timedelta(days=46)
    holidays[cinzas] = "Quarta de Cinzas"

    # Sexta-feira Santa: 2 dias antes da Pascoa
    sexta_santa = easter - datetime.timedelta(days=2)
    holidays[sexta_santa] = "Sexta-Feira Santa"

    # Corpus Christi: 60 dias apos a Pascoa
    corpus = easter + datetime.timedelta(days=60)
    holidays[corpus] = "Corpus Christi"

    return holidays


def classify_shift_date(date_val, year: int = None) -> dict:
    """
    Classifica uma data de turno.
    Retorna dict com 'tipo' (FERIADO, DOMINGO, SABADO, NORMAL) e 'descricao'.
    """
    if date_val is None:
        return {'tipo': 'NORMAL', 'descricao': ''}

    # Converter para datetime.date se necessario
    if isinstance(date_val, datetime.datetime):
        d = date_val.date()
    elif isinstance(date_val, datetime.date):
        d = date_val
    elif isinstance(date_val, str):
        # Tenta formatos comuns
        for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
            try:
                d = datetime.datetime.strptime(date_val.strip(), fmt).date()
                break
            except ValueError:
                continue
        else:
            return {'tipo': 'NORMAL', 'descricao': ''}
    else:
        return {'tipo': 'NORMAL', 'descricao': ''}

    if year is None:
        year = d.year

    holidays = get_all_holidays(year)

    if d in holidays:
        return {'tipo': 'FERIADO', 'descricao': holidays[d]}
    elif d.weekday() == 6:  # Domingo
        return {'tipo': 'DOMINGO', 'descricao': 'Domingo'}
    elif d.weekday() == 5:  # Sabado
        return {'tipo': 'SABADO', 'descricao': 'Sabado'}
    else:
        return {'tipo': 'NORMAL', 'descricao': ''}


def check_consecutive_days(shifts: list, max_consecutive: int = 6) -> list:
    """
    Verifica se ha sequencias de dias consecutivos trabalhados acima do limite.
    Retorna lista de alertas.
    """
    if not shifts:
        return []

    # Extrair datas unicas dos turnos
    dates = set()
    for s in shifts:
        d = s.get('data', '')
        if isinstance(d, str) and d:
            for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
                try:
                    dates.add(datetime.datetime.strptime(d.strip(), fmt).date())
                    break
                except ValueError:
                    continue
        elif isinstance(d, (datetime.date, datetime.datetime)):
            dates.add(d if isinstance(d, datetime.date) else d.date())

    if len(dates) <= max_consecutive:
        return []

    sorted_dates = sorted(dates)
    alerts = []
    streak = 1

    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
            streak += 1
            if streak > max_consecutive:
                alerts.append({
                    'severidade': 'ALTA',
                    'mensagem': (
                        f"Sequencia de {streak} dias consecutivos trabalhados "
                        f"({sorted_dates[i - streak + 1].strftime('%d/%m')} a "
                        f"{sorted_dates[i].strftime('%d/%m')}). "
                        f"Maximo legal: {max_consecutive} dias."
                    )
                })
        else:
            streak = 1

    return alerts
