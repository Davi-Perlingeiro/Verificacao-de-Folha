from dataclasses import dataclass, field
from engine.name_matcher import match_employees
from engine.calculations import validate_shift, check_overlapping_shifts
from engine.labor_calculations import enrich_excel_data
from engine.holidays import classify_shift_date, check_consecutive_days


@dataclass
class Divergence:
    employee_name: str
    field: str
    excel_value: float
    pdf_value: float
    difference: float
    severity: str  # 'CRITICO', 'ALERTA', 'INFO'
    description: str


@dataclass
class EmployeeComparison:
    nome_excel: str
    nome_pdf: str
    match_confidence: float
    status: str  # 'OK', 'DIVERGENTE', 'AUSENTE_FOLHA', 'AUSENTE_PONTO'
    divergences: list = field(default_factory=list)
    excel_data: dict = field(default_factory=dict)
    pdf_data: dict = field(default_factory=dict)


@dataclass
class ComparisonReport:
    comparisons: list = field(default_factory=list)
    excel_only: list = field(default_factory=list)  # Nomes no ponto mas nao na folha
    pdf_only: list = field(default_factory=list)    # Nomes na folha mas nao no ponto
    alerts: list = field(default_factory=list)
    total_excel_employees: int = 0
    total_pdf_employees: int = 0
    total_matched: int = 0
    total_divergent: int = 0
    total_ok: int = 0


# Tolerancias padrao
DEFAULT_HOUR_TOLERANCE = 0.5      # 30 minutos
DEFAULT_MONEY_TOLERANCE = 1.00    # R$ 1.00


def compare_payrolls(excel_data: dict, pdf_data: dict,
                     hour_tolerance: float = None,
                     money_tolerance: float = None,
                     corrections: dict = None) -> ComparisonReport:
    """
    Compara folha de ponto (Excel) com folha de pagamento (PDF).
    Excel data: dict[nome] -> dados agregados do ponto
    PDF data: dict com 'employees' -> dict[nome] -> dados da folha
    """
    h_tol = hour_tolerance if hour_tolerance is not None else DEFAULT_HOUR_TOLERANCE
    m_tol = money_tolerance if money_tolerance is not None else DEFAULT_MONEY_TOLERANCE

    pdf_employees = pdf_data.get('employees', {})

    excel_names = list(excel_data.keys())
    pdf_names = list(pdf_employees.keys())

    matching = match_employees(excel_names, pdf_names, corrections=corrections)

    report = ComparisonReport(
        total_excel_employees=len(excel_names),
        total_pdf_employees=len(pdf_names),
    )

    # Processar funcionarios matched
    for excel_name, pdf_name, norm_key, confidence in matching['matched']:
        excel_emp = excel_data[excel_name]
        pdf_emp = pdf_employees[pdf_name]

        # Enriquecer dados do Excel com calculos trabalhistas
        enrich_excel_data(excel_emp)

        divergences = _compare_employee(excel_name, excel_emp, pdf_emp, h_tol, m_tol)

        status = 'OK' if not divergences else 'DIVERGENTE'

        comp = EmployeeComparison(
            nome_excel=excel_name,
            nome_pdf=pdf_name,
            match_confidence=confidence,
            status=status,
            divergences=divergences,
            excel_data=excel_emp,
            pdf_data=pdf_emp,
        )
        report.comparisons.append(comp)

        if status == 'OK':
            report.total_ok += 1
        else:
            report.total_divergent += 1

        # Alertas de turnos individuais
        for shift in excel_emp.get('turnos', []):
            shift_alerts = validate_shift(shift)
            for alert in shift_alerts:
                report.alerts.append({
                    'funcionario': excel_name,
                    'severidade': alert['severidade'],
                    'mensagem': alert['mensagem'],
                })

            # Alerta de feriado/domingo
            date_info = classify_shift_date(shift.get('data', ''))
            if date_info['tipo'] in ('FERIADO', 'DOMINGO'):
                report.alerts.append({
                    'funcionario': excel_name,
                    'severidade': 'MEDIA',
                    'mensagem': f"Trabalho em {date_info['tipo']}: {shift.get('data', '')} - {date_info['descricao']}",
                })

        # Alertas de sobreposicao
        overlap_alerts = check_overlapping_shifts(excel_emp.get('turnos', []))
        for alert in overlap_alerts:
            report.alerts.append({
                'funcionario': excel_name,
                'severidade': alert['severidade'],
                'mensagem': alert['mensagem'],
            })

        # Alertas de dias consecutivos
        consec_alerts = check_consecutive_days(excel_emp.get('turnos', []))
        for alert in consec_alerts:
            report.alerts.append({
                'funcionario': excel_name,
                'severidade': alert['severidade'],
                'mensagem': alert['mensagem'],
            })

    report.total_matched = len(matching['matched'])

    # Funcionarios apenas no Excel (faltando na folha de pagamento)
    for name in matching['excel_only']:
        emp = excel_data[name]
        comp = EmployeeComparison(
            nome_excel=name,
            nome_pdf='',
            match_confidence=0.0,
            status='AUSENTE_FOLHA',
            excel_data=emp,
        )
        report.comparisons.append(comp)
        report.excel_only.append(name)

    # Funcionarios apenas no PDF (faltando no ponto)
    for name in matching['pdf_only']:
        emp = pdf_employees[name]
        comp = EmployeeComparison(
            nome_excel='',
            nome_pdf=name,
            match_confidence=0.0,
            status='AUSENTE_PONTO',
            pdf_data=emp,
        )
        report.comparisons.append(comp)
        report.pdf_only.append(name)

    return report


def _compare_employee(name: str, excel: dict, pdf: dict,
                      h_tol: float, m_tol: float) -> list:
    """Compara dados de um funcionario entre Excel e PDF."""
    divergences = []

    # 1. Horas Trabalhadas
    excel_hours = excel.get('total_horas', 0)
    pdf_hours = pdf.get('salario_base_horas', 0)
    if abs(excel_hours - pdf_hours) > h_tol:
        divergences.append(Divergence(
            employee_name=name,
            field='Horas Trabalhadas',
            excel_value=excel_hours,
            pdf_value=pdf_hours,
            difference=excel_hours - pdf_hours,
            severity='CRITICO',
            description=f"Horas divergentes: Ponto={excel_hours:.0f}h, Folha={pdf_hours:.0f}h (diff={excel_hours - pdf_hours:+.0f}h)"
        ))

    # 2. Salario Base
    excel_sal = excel.get('total_salario_base', 0)
    pdf_sal = pdf.get('salario_base_valor', 0)
    if abs(excel_sal - pdf_sal) > m_tol:
        divergences.append(Divergence(
            employee_name=name,
            field='Salario Base',
            excel_value=excel_sal,
            pdf_value=pdf_sal,
            difference=excel_sal - pdf_sal,
            severity='CRITICO',
            description=f"Salario base divergente: Ponto=R${excel_sal:.2f}, Folha=R${pdf_sal:.2f}"
        ))

    # 3. Horas Noturnas
    excel_not_h = excel.get('total_noturno_horas', 0)
    pdf_not_h = pdf.get('noturno_horas', 0)
    if abs(excel_not_h - pdf_not_h) > h_tol:
        divergences.append(Divergence(
            employee_name=name,
            field='Horas Noturnas',
            excel_value=excel_not_h,
            pdf_value=pdf_not_h,
            difference=excel_not_h - pdf_not_h,
            severity='CRITICO',
            description=f"Horas noturnas divergentes: Ponto={excel_not_h:.2f}h, Folha={pdf_not_h:.2f}h"
        ))

    # 4. DSR
    excel_dsr = excel.get('total_dsr', 0)
    pdf_dsr = pdf.get('dsr', 0)
    if abs(excel_dsr - pdf_dsr) > m_tol:
        divergences.append(Divergence(
            employee_name=name,
            field='DSR',
            excel_value=excel_dsr,
            pdf_value=pdf_dsr,
            difference=excel_dsr - pdf_dsr,
            severity='ALERTA',
            description=f"DSR divergente: Ponto=R${excel_dsr:.2f}, Folha=R${pdf_dsr:.2f}"
        ))

    # 5. Ajuda de Custo
    excel_ajuda = excel.get('total_ajuda_custo', 0)
    pdf_ajuda = pdf.get('ajuda_custo', 0)
    if abs(excel_ajuda - pdf_ajuda) > m_tol:
        divergences.append(Divergence(
            employee_name=name,
            field='Ajuda de Custo',
            excel_value=excel_ajuda,
            pdf_value=pdf_ajuda,
            difference=excel_ajuda - pdf_ajuda,
            severity='ALERTA',
            description=f"Ajuda de custo divergente: Ponto=R${excel_ajuda:.2f}, Folha=R${pdf_ajuda:.2f}"
        ))

    # 6. Valor Adicional Noturno
    excel_not_v = excel.get('total_ad_noturno', 0)
    pdf_not_v = pdf.get('noturno_valor', 0)
    if abs(excel_not_v - pdf_not_v) > m_tol:
        divergences.append(Divergence(
            employee_name=name,
            field='Adicional Noturno (R$)',
            excel_value=excel_not_v,
            pdf_value=pdf_not_v,
            difference=excel_not_v - pdf_not_v,
            severity='CRITICO',
            description=f"Valor noturno divergente: Ponto=R${excel_not_v:.2f}, Folha=R${pdf_not_v:.2f}"
        ))

    # === NOVAS COMPARACOES (Fase 1) ===

    # 7. Repouso Remunerado (calculado vs PDF)
    calc_repouso = excel.get('_calc_repouso', 0)
    pdf_repouso = pdf.get('repouso', 0)
    if calc_repouso > 0 or pdf_repouso > 0:
        if abs(calc_repouso - pdf_repouso) > m_tol:
            divergences.append(Divergence(
                employee_name=name,
                field='Repouso Remunerado',
                excel_value=calc_repouso,
                pdf_value=pdf_repouso,
                difference=calc_repouso - pdf_repouso,
                severity='ALERTA',
                description=f"Repouso divergente: Calculado=R${calc_repouso:.2f}, Folha=R${pdf_repouso:.2f}"
            ))

    # 8. Ferias Intermitente (calculado vs PDF)
    calc_ferias = excel.get('_calc_ferias', 0)
    pdf_ferias = pdf.get('ferias', 0)
    if calc_ferias > 0 or pdf_ferias > 0:
        if abs(calc_ferias - pdf_ferias) > m_tol:
            divergences.append(Divergence(
                employee_name=name,
                field='Ferias Intermitente',
                excel_value=calc_ferias,
                pdf_value=pdf_ferias,
                difference=calc_ferias - pdf_ferias,
                severity='ALERTA',
                description=f"Ferias divergente: Calculado=R${calc_ferias:.2f}, Folha=R${pdf_ferias:.2f}"
            ))

    # 9. 13o Salario (calculado vs PDF)
    calc_decimo = excel.get('_calc_decimo', 0)
    pdf_decimo = pdf.get('decimo', 0)
    if calc_decimo > 0 or pdf_decimo > 0:
        if abs(calc_decimo - pdf_decimo) > m_tol:
            divergences.append(Divergence(
                employee_name=name,
                field='13o Salario',
                excel_value=calc_decimo,
                pdf_value=pdf_decimo,
                difference=calc_decimo - pdf_decimo,
                severity='ALERTA',
                description=f"13o divergente: Calculado=R${calc_decimo:.2f}, Folha=R${pdf_decimo:.2f}"
            ))

    # 10. INSS Folha (calculado vs PDF)
    calc_inss_folha = excel.get('_calc_inss_folha', 0)
    pdf_inss_folha = pdf.get('inss_folha', 0)
    if calc_inss_folha > 0 or pdf_inss_folha > 0:
        if abs(calc_inss_folha - pdf_inss_folha) > m_tol:
            divergences.append(Divergence(
                employee_name=name,
                field='INSS Folha',
                excel_value=calc_inss_folha,
                pdf_value=pdf_inss_folha,
                difference=calc_inss_folha - pdf_inss_folha,
                severity='INFO',
                description=f"INSS Folha divergente: Calculado=R${calc_inss_folha:.2f}, Folha=R${pdf_inss_folha:.2f}"
            ))

    # 11. INSS 13o (calculado vs PDF)
    calc_inss_13 = excel.get('_calc_inss_13', 0)
    pdf_inss_13 = pdf.get('inss_13', 0)
    if calc_inss_13 > 0 or pdf_inss_13 > 0:
        if abs(calc_inss_13 - pdf_inss_13) > m_tol:
            divergences.append(Divergence(
                employee_name=name,
                field='INSS 13o',
                excel_value=calc_inss_13,
                pdf_value=pdf_inss_13,
                difference=calc_inss_13 - pdf_inss_13,
                severity='INFO',
                description=f"INSS 13o divergente: Calculado=R${calc_inss_13:.2f}, Folha=R${pdf_inss_13:.2f}"
            ))

    # 12. Total Liquido (Excel total_a_pagar vs PDF total_liquido)
    excel_total = excel.get('total_a_pagar', 0)
    pdf_total = pdf.get('total_liquido', 0)
    if excel_total > 0 or pdf_total > 0:
        if abs(excel_total - pdf_total) > m_tol:
            divergences.append(Divergence(
                employee_name=name,
                field='Total Liquido',
                excel_value=excel_total,
                pdf_value=pdf_total,
                difference=excel_total - pdf_total,
                severity='CRITICO',
                description=f"Total liquido divergente: Ponto=R${excel_total:.2f}, Folha=R${pdf_total:.2f}"
            ))

    return divergences
