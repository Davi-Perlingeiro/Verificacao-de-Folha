import datetime


def calculate_night_hours(start: datetime.datetime, end: datetime.datetime) -> float:
    """
    Calcula horas dentro da janela noturna (22:00-05:00).
    Retorna float de horas noturnas.
    """
    if start is None or end is None:
        return 0.0

    # Ajustar se end < start (turno cruza meia-noite)
    if end <= start:
        end = end + datetime.timedelta(days=1)

    total_night = 0.0
    current = start

    while current < end:
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)

        # Janela noturna: 22:00 do dia ate 05:00 do dia seguinte
        night_start = day_start.replace(hour=22)
        night_end = day_start + datetime.timedelta(days=1, hours=5)

        # Tambem considerar a janela noturna do dia anterior (00:00-05:00)
        night_start_prev = day_start.replace(hour=0)
        night_end_prev = day_start.replace(hour=5)

        # Calcular sobreposicao com janela 00:00-05:00 do dia atual
        overlap_prev = _overlap_hours(current, end, night_start_prev, night_end_prev)

        # Calcular sobreposicao com janela 22:00-05:00+1
        overlap_main = _overlap_hours(current, end, night_start, night_end)

        total_night += overlap_prev + overlap_main

        # Avancar para o proximo dia
        current = day_start + datetime.timedelta(days=1)

    return total_night


def _overlap_hours(s1, e1, s2, e2) -> float:
    """Calcula horas de sobreposicao entre dois intervalos."""
    start = max(s1, s2)
    end = min(e1, e2)
    if start >= end:
        return 0.0
    return (end - start).total_seconds() / 3600.0


def validate_shift(shift: dict) -> list:
    """
    Aplica regras de alerta a um turno individual.
    Retorna lista de dicts com {severidade, mensagem}.
    """
    alerts = []
    horas = shift.get('horas_trabalhadas', 0)

    if horas > 12:
        alerts.append({
            'severidade': 'ALTA',
            'mensagem': f"Jornada acima de 12h: {horas:.1f}h"
        })
    elif horas < 4 and horas > 0:
        alerts.append({
            'severidade': 'MEDIA',
            'mensagem': f"Jornada abaixo de 4h: {horas:.1f}h"
        })

    noturno = shift.get('noturno_horas', 0)
    if noturno > horas and horas > 0:
        alerts.append({
            'severidade': 'MEDIA',
            'mensagem': f"Horas noturnas ({noturno:.1f}h) maiores que horas trabalhadas ({horas:.1f}h)"
        })

    return alerts


def check_overlapping_shifts(shifts: list) -> list:
    """
    Verifica sobreposicao de turnos para o mesmo funcionario.
    Retorna lista de alertas.
    """
    alerts = []
    sorted_shifts = sorted(
        [s for s in shifts if s.get('horario_inicial')],
        key=lambda x: x['horario_inicial']
    )

    for i in range(len(sorted_shifts) - 1):
        current = sorted_shifts[i]
        next_s = sorted_shifts[i + 1]

        end_current = current.get('horario_final')
        start_next = next_s.get('horario_inicial')

        if end_current and start_next and end_current > start_next:
            alerts.append({
                'severidade': 'ALTA',
                'mensagem': (
                    f"Sobreposicao de turnos: "
                    f"{current.get('data', '')} {current.get('evento', '')} "
                    f"termina depois do inicio de "
                    f"{next_s.get('data', '')} {next_s.get('evento', '')}"
                )
            })

    return alerts
