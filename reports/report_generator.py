import io
import pandas as pd
from utils.formatting import format_br_currency, hours_to_hhmm


def generate_comparison_dataframe(report) -> pd.DataFrame:
    """Gera DataFrame com comparacao detalhada para exibicao."""
    rows = []
    for comp in report.comparisons:
        excel = comp.excel_data or {}
        pdf = comp.pdf_data or {}

        excel_hours = excel.get('total_horas', 0)
        pdf_hours = pdf.get('salario_base_horas', 0)
        excel_sal = excel.get('total_salario_base', 0)
        pdf_sal = pdf.get('salario_base_valor', 0)
        excel_not = excel.get('total_noturno_horas', 0)
        pdf_not = pdf.get('noturno_horas', 0)
        excel_dsr = excel.get('total_dsr', 0)
        pdf_dsr = pdf.get('dsr', 0)
        excel_ajuda = excel.get('total_ajuda_custo', 0)
        pdf_ajuda = pdf.get('ajuda_custo', 0)

        # Novos campos (Fase 1)
        calc_repouso = excel.get('_calc_repouso', 0)
        pdf_repouso = pdf.get('repouso', 0)
        calc_ferias = excel.get('_calc_ferias', 0)
        pdf_ferias = pdf.get('ferias', 0)
        calc_decimo = excel.get('_calc_decimo', 0)
        pdf_decimo = pdf.get('decimo', 0)
        excel_total = excel.get('total_a_pagar', 0)
        pdf_total = pdf.get('total_liquido', 0)

        nome = comp.nome_excel or comp.nome_pdf

        row = {
            'Funcionario': nome,
            'Status': _status_label(comp.status),
            'Horas Ponto': hours_to_hhmm(excel_hours) if excel_hours else '-',
            'Horas Folha': hours_to_hhmm(pdf_hours) if pdf_hours else '-',
            'Diff Horas': f"{excel_hours - pdf_hours:+.0f}h" if (excel_hours and pdf_hours) else '-',
            'Salario Ponto': format_br_currency(excel_sal) if excel_sal else '-',
            'Salario Folha': format_br_currency(pdf_sal) if pdf_sal else '-',
            'Not. Ponto (h)': f"{excel_not:.2f}" if excel_not else '-',
            'Not. Folha (h)': f"{pdf_not:.2f}" if pdf_not else '-',
            'DSR Ponto': format_br_currency(excel_dsr) if excel_dsr else '-',
            'DSR Folha': format_br_currency(pdf_dsr) if pdf_dsr else '-',
            'Ajuda Ponto': format_br_currency(excel_ajuda) if excel_ajuda else '-',
            'Ajuda Folha': format_br_currency(pdf_ajuda) if pdf_ajuda else '-',
            'Repouso Calc.': format_br_currency(calc_repouso) if calc_repouso else '-',
            'Repouso Folha': format_br_currency(pdf_repouso) if pdf_repouso else '-',
            'Ferias Calc.': format_br_currency(calc_ferias) if calc_ferias else '-',
            'Ferias Folha': format_br_currency(pdf_ferias) if pdf_ferias else '-',
            '13o Calc.': format_br_currency(calc_decimo) if calc_decimo else '-',
            '13o Folha': format_br_currency(pdf_decimo) if pdf_decimo else '-',
            'Total Ponto': format_br_currency(excel_total) if excel_total else '-',
            'Total Folha': format_br_currency(pdf_total) if pdf_total else '-',
            'Divergencias': len(comp.divergences),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        # Ordenar: divergentes primeiro, depois ausentes, depois OK
        status_order = {'DIVERGENTE': 0, 'AUSENTE NA FOLHA': 1, 'AUSENTE NO PONTO': 2, 'OK': 3}
        df['_sort'] = df['Status'].map(status_order).fillna(4)
        df = df.sort_values(['_sort', 'Funcionario']).drop(columns=['_sort']).reset_index(drop=True)
    return df


def generate_divergence_detail(report) -> pd.DataFrame:
    """Gera DataFrame com detalhes de todas as divergencias."""
    rows = []
    for comp in report.comparisons:
        for div in comp.divergences:
            rows.append({
                'Funcionario': div.employee_name,
                'Campo': div.field,
                'Valor Ponto': f"{div.excel_value:.2f}",
                'Valor Folha': f"{div.pdf_value:.2f}",
                'Diferenca': f"{div.difference:+.2f}",
                'Severidade': div.severity,
                'Descricao': div.description,
            })
    return pd.DataFrame(rows)


def generate_missing_employees_df(report) -> tuple:
    """Gera DataFrames de funcionarios ausentes."""
    # Ausentes na folha de pagamento
    missing_folha = []
    for comp in report.comparisons:
        if comp.status == 'AUSENTE_FOLHA':
            excel = comp.excel_data
            missing_folha.append({
                'Funcionario': comp.nome_excel,
                'Horas': hours_to_hhmm(excel.get('total_horas', 0)),
                'Salario Base': format_br_currency(excel.get('total_salario_base', 0)),
                'DSR': format_br_currency(excel.get('total_dsr', 0)),
                'Ajuda Custo': format_br_currency(excel.get('total_ajuda_custo', 0)),
                'Turnos': excel.get('num_turnos', 0),
            })

    # Ausentes no ponto
    missing_ponto = []
    for comp in report.comparisons:
        if comp.status == 'AUSENTE_PONTO':
            pdf = comp.pdf_data
            missing_ponto.append({
                'Funcionario': comp.nome_pdf,
                'Horas': hours_to_hhmm(pdf.get('salario_base_horas', 0)),
                'Salario Base': format_br_currency(pdf.get('salario_base_valor', 0)),
                'DSR': format_br_currency(pdf.get('dsr', 0)),
            })

    return pd.DataFrame(missing_folha), pd.DataFrame(missing_ponto)


def generate_alerts_df(report) -> pd.DataFrame:
    """Gera DataFrame de alertas."""
    if not report.alerts:
        return pd.DataFrame(columns=['Funcionario', 'Severidade', 'Mensagem'])
    df = pd.DataFrame(report.alerts, columns=['funcionario', 'severidade', 'mensagem'])
    df.columns = ['Funcionario', 'Severidade', 'Mensagem']
    severity_order = {'ALTA': 0, 'MEDIA': 1, 'BAIXA': 2}
    df['_sort'] = df['Severidade'].map(severity_order).fillna(3)
    return df.sort_values(['_sort', 'Funcionario']).drop(columns=['_sort']).reset_index(drop=True)


def generate_excel_report(report) -> bytes:
    """Gera relatorio Excel completo para download."""
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Resumo
        summary_data = {
            'Metrica': [
                'Total Funcionarios no Ponto',
                'Total Funcionarios na Folha',
                'Funcionarios Matched',
                'Funcionarios OK',
                'Funcionarios com Divergencia',
                'Ausentes na Folha',
                'Ausentes no Ponto',
            ],
            'Valor': [
                report.total_excel_employees,
                report.total_pdf_employees,
                report.total_matched,
                report.total_ok,
                report.total_divergent,
                len(report.excel_only),
                len(report.pdf_only),
            ]
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Resumo', index=False)

        # Sheet 2: Comparacao Detalhada
        comp_df = generate_comparison_dataframe(report)
        if not comp_df.empty:
            comp_df.to_excel(writer, sheet_name='Comparacao Detalhada', index=False)

        # Sheet 3: Divergencias
        div_df = generate_divergence_detail(report)
        if not div_df.empty:
            div_df.to_excel(writer, sheet_name='Divergencias', index=False)

        # Sheet 4: Funcionarios Ausentes
        missing_folha, missing_ponto = generate_missing_employees_df(report)
        if not missing_folha.empty:
            missing_folha.to_excel(writer, sheet_name='Ausentes na Folha', index=False)
        if not missing_ponto.empty:
            missing_ponto.to_excel(writer, sheet_name='Ausentes no Ponto', index=False)

        # Sheet 5: Alertas
        alerts_df = generate_alerts_df(report)
        if not alerts_df.empty:
            alerts_df.to_excel(writer, sheet_name='Alertas', index=False)

    return output.getvalue()


def generate_pdf_report(report) -> bytes:
    """Gera relatorio PDF completo para download."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=15*mm, rightMargin=15*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontSize=16,
                                  spaceAfter=12)
    subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Heading2'], fontSize=12,
                                     spaceAfter=8, spaceBefore=16)
    normal_style = styles['Normal']

    elements = []

    # Titulo
    elements.append(Paragraph("Relatorio de Verificacao - Folha de Pagamento", title_style))
    elements.append(Paragraph("SF Servicos Selecao e Agenciamento LTDA", normal_style))
    elements.append(Spacer(1, 10*mm))

    # Resumo
    elements.append(Paragraph("Resumo", subtitle_style))
    summary_data = [
        ['Metrica', 'Valor'],
        ['Funcionarios no Ponto', str(report.total_excel_employees)],
        ['Funcionarios na Folha', str(report.total_pdf_employees)],
        ['Matched', str(report.total_matched)],
        ['OK', str(report.total_ok)],
        ['Divergentes', str(report.total_divergent)],
        ['Ausentes na Folha', str(len(report.excel_only))],
        ['Ausentes no Ponto', str(len(report.pdf_only))],
    ]
    t = Table(summary_data, colWidths=[120*mm, 40*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
    ]))
    elements.append(t)

    # Divergencias
    div_df = generate_divergence_detail(report)
    if not div_df.empty:
        elements.append(Paragraph("Divergencias Encontradas", subtitle_style))
        div_data = [['Funcionario', 'Campo', 'Ponto', 'Folha', 'Diff', 'Sev.']]
        for _, row in div_df.iterrows():
            div_data.append([
                Paragraph(str(row['Funcionario'])[:25], normal_style),
                str(row['Campo'])[:20],
                str(row['Valor Ponto']),
                str(row['Valor Folha']),
                str(row['Diferenca']),
                str(row['Severidade']),
            ])

        col_widths = [45*mm, 35*mm, 25*mm, 25*mm, 20*mm, 18*mm]
        t = Table(div_data, colWidths=col_widths, repeatRows=1)
        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]
        # Colorir linhas por severidade
        for i, (_, row) in enumerate(div_df.iterrows(), 1):
            if row['Severidade'] == 'CRITICO':
                style_commands.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#ffcccc')))
            elif row['Severidade'] == 'ALERTA':
                style_commands.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#ffffcc')))

        t.setStyle(TableStyle(style_commands))
        elements.append(t)

    # Ausentes
    missing_folha, missing_ponto = generate_missing_employees_df(report)
    if not missing_folha.empty:
        elements.append(Paragraph("Ausentes na Folha de Pagamento", subtitle_style))
        aus_data = [list(missing_folha.columns)]
        for _, row in missing_folha.iterrows():
            aus_data.append([str(v) for v in row.values])
        t = Table(aus_data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e67e22')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(t)

    doc.build(elements)
    return output.getvalue()


def _status_label(status: str) -> str:
    """Converte status interno para label legivel."""
    labels = {
        'OK': 'OK',
        'DIVERGENTE': 'DIVERGENTE',
        'AUSENTE_FOLHA': 'AUSENTE NA FOLHA',
        'AUSENTE_PONTO': 'AUSENTE NO PONTO',
    }
    return labels.get(status, status)
