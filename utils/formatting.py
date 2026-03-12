import datetime
import re


def parse_br_number(value) -> float:
    """Converte numero brasileiro ('176,88' ou '1.019,41') para float."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    # Remove pontos de milhar e troca virgula por ponto
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def format_br_currency(value: float) -> str:
    """Formata float como moeda brasileira: R$ 1.234,56"""
    if value < 0:
        return f"-R$ {abs(value):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def format_br_number(value: float, decimals: int = 2) -> str:
    """Formata float com virgula decimal: 1.234,56"""
    fmt = f"{{:,.{decimals}f}}"
    return fmt.format(value).replace(',', 'X').replace('.', ',').replace('X', '.')


def parse_pdf_hours(text: str) -> float:
    """Converte formato PDF de horas '024:00' ou '015:38' para float."""
    if not text:
        return 0.0
    m = re.match(r'(\d+):(\d{2})', str(text).strip())
    if m:
        hours = int(m.group(1))
        minutes = int(m.group(2))
        return hours + minutes / 60.0
    return 0.0


def parse_time_to_hours(time_val) -> float:
    """Converte datetime.time, timedelta ou string para float de horas."""
    if time_val is None:
        return 0.0
    if isinstance(time_val, datetime.timedelta):
        return time_val.total_seconds() / 3600.0
    if isinstance(time_val, datetime.time):
        return time_val.hour + time_val.minute / 60.0 + time_val.second / 3600.0
    if isinstance(time_val, (int, float)):
        return float(time_val)
    s = str(time_val).strip()
    # Tenta formato HH:MM:SS ou HH:MM
    m = re.match(r'(\d+):(\d{2})(?::(\d{2}))?', s)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2))
        sec = int(m.group(3)) if m.group(3) else 0
        return h + mi / 60.0 + sec / 3600.0
    # Tenta formato brasileiro com virgula: "12,00"
    s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def hours_to_hhmm(hours: float) -> str:
    """Converte float de horas para formato HH:MM."""
    if hours < 0:
        return f"-{hours_to_hhmm(abs(hours))}"
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h += 1
        m = 0
    return f"{h:02d}:{m:02d}"
