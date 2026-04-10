import sys
import os

# Adicionar diretorio raiz ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from parsers.excel_parser import parse_folha_de_ponto
from parsers.pdf_parser import parse_folha_de_pagamento
from parsers.medicao_parser import parse_medicao
from engine.comparison import compare_payrolls
from engine.holidays import classify_shift_date
from engine.payroll_builder import build_payroll, get_summary_by_employee, DEFAULT_PARAMS
from engine.database import (
    save_comparison, get_comparison_history, get_employee_trend,
    save_name_correction, get_name_corrections, delete_name_correction,
)
from reports.report_generator import (
    generate_comparison_dataframe,
    generate_divergence_detail,
    generate_missing_employees_df,
    generate_alerts_df,
    generate_excel_report,
    generate_pdf_report,
)
from reports.payroll_export import export_payroll_excel
from utils.formatting import format_br_currency, hours_to_hhmm


def _render_preparo_contabilidade():
    """Modulo de Preparo de Contabilidade - transforma Medicao em Folha."""
    st.title("Preparo Contabilidade")
    st.markdown("**SF Servicos Selecao e Agenciamento LTDA** - Fechamento de Folha de Pagamento")

    # --- Sidebar: parametros ---
    with st.sidebar:
        st.header("Parametros da Folha")

        regiao = st.selectbox(
            "Regiao",
            ["BH", "RJ"],
            index=0,
            help="BH: Sal.Hora R$7,66 (base R$1.685,20) | RJ: Sal.Hora R$7,368 (base R$1.621,00)"
        )

        if regiao == "RJ":
            default_sal_base = 1621.00
        else:
            default_sal_base = 1685.20

        sal_base = st.number_input(
            "Salario Base Mensal (R$)",
            min_value=0.0, value=default_sal_base, step=1.0,
            format="%.2f",
            help="BH: R$ 1.685,20 | RJ: R$ 1.621,00"
        )
        divisor = st.number_input(
            "Divisor de Horas",
            min_value=1, value=220, step=1,
            help="Horas mensais para calculo do salario hora (padrao: 220h)"
        )

        sal_hora_calc = sal_base / divisor if divisor > 0 else 0
        st.info(f"Salario Hora: **R$ {sal_hora_calc:.3f}**")

        default_ajuda = 40.0 if regiao == "BH" else 30.0
        ajuda_custo = st.number_input(
            "Ajuda de Custo (R$)",
            min_value=0.0, value=default_ajuda, step=1.0,
            format="%.2f",
        )
        vt_desc = st.number_input(
            "Desconto VT (%)",
            min_value=0.0, max_value=100.0, value=0.0, step=0.5,
            format="%.1f",
        ) / 100.0

        st.divider()
        st.header("Upload")
        medicao_file = st.file_uploader(
            "Relatorio de Medicao (.xlsx)",
            type=['xlsx'],
            help="Arquivo extraido do sistema interno",
            key='medicao_upload',
        )

        st.divider()
        if regiao == "BH":
            st.header("Regras BH")
            aplicar_regras_bh = st.checkbox(
                "Aplicar regras de acrescimo BH",
                value=False,
                help=(
                    "Acrescimos cumulativos na Ajuda de Custo:\n"
                    "- Regra 1: Setores SCP Shop. Monte Carmo, Shopping Ponteio, Aeroporto Lagoa Santa (+R$30)\n"
                    "- Regra 2: Saida a partir das 23:00h (+R$15)\n"
                    "- Regra 3: Diaria 12h (18:00-06:00) (+R$15)\n"
                    "- Regra 4: Diaria 12h (19:00-07:00) (+R$15)"
                ),
            )
        else:
            aplicar_regras_bh = False

    if not medicao_file:
        st.info("Faca upload do **Relatorio de Medicao** na barra lateral para iniciar o preparo da folha.")
        st.markdown("""
### Como usar:
1. Na barra lateral, configure os parametros (salario base, ajuda de custo, etc.)
2. Faca upload do **Relatorio de Medicao** extraido do sistema interno
3. Revise os calculos na tabela
4. Ajuste valores individuais se necessario (Desc. Adiantamento, Sal. Familia)
5. Baixe a planilha final formatada

### Calculos aplicados automaticamente:
- **Adicional Noturno**: Hora ficta CLT Art. 73 (22h-05h, fator 8/7) + 20%
- **DSR**: 1/6 sobre (Salario + Gratificacao + Ad. Noturno)
- **Ferias**: 1/12 sobre base + 1/3 constitucional
- **13o Salario**: 1/12 sobre base
- **INSS**: Aliquotas progressivas 2026 (7,5% a 14%) por funcionario
        """)
        return

    # Processar
    params = {
        'salario_base_mensal': sal_base,
        'divisor_horas': divisor,
        'dsr_fator': 1 / 6,
        'ferias_fator': 1 / 12,
        'ferias_adicional': 1 / 3,
        'decimo_fator': 1 / 12,
        'vt_desconto': vt_desc,
        'ajuda_custo': ajuda_custo,
    }

    try:
        with st.spinner("Processando relatorio de medicao..."):
            turnos = parse_medicao(medicao_file.read())
            medicao_file.seek(0)

            if not turnos:
                st.error("Nenhum turno encontrado no relatorio de medicao.")
                return

            df = build_payroll(turnos, params, aplicar_regras_bh=aplicar_regras_bh)
            if df.empty:
                st.error("Erro ao processar turnos.")
                return

        st.session_state['payroll_df'] = df
        st.session_state['payroll_params'] = params

    except Exception as e:
        st.error(f"Erro ao processar: {e}")
        import traceback
        st.code(traceback.format_exc())
        return

    df = st.session_state.get('payroll_df', df)

    # Metricas
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Turnos", len(df))
    with col2:
        st.metric("Funcionarios", df['nome'].nunique())
    with col3:
        st.metric("Total Horas", f"{df['horas_trab_num'].sum():.1f}h")
    with col4:
        st.metric("Horas Noturnas", f"{df['horas_not_num'].sum():.1f}h")
    with col5:
        st.metric("Total a Pagar", format_br_currency(df['total_pagar'].sum()))

    st.divider()

    # Abas
    tab_det, tab_resumo, tab_download = st.tabs([
        "Detalhamento por Turno",
        "Resumo por Funcionario",
        "Download",
    ])

    with tab_det:
        st.subheader("Detalhamento Completo")

        # Colunas para exibir (mais legivel)
        display_cols = {
            'nome': 'Nome',
            'data': 'Data',
            'evento': 'Local',
            'horario_inicial': 'Entrada',
            'horario_final': 'Saida',
            'horas_trab_num': 'Horas',
            'horas_not_num': 'H.Noturnas',
            'salario': 'Salario',
            'ad_noturno_valor': 'Ad.Not.20%',
            'dsr': 'DSR',
            'ferias': 'Ferias',
            'adic_ferias': 'Ad.Ferias',
            'decimo': '13o',
            'inss': 'INSS',
            'inss_13': 'INSS 13o',
            'sal_liquido': 'Sal.Liquido',
            'ajuda_custo': 'Aj.Custo',
            'total_pagar': 'Total',
        }

        df_display = df[list(display_cols.keys())].copy()
        df_display.columns = list(display_cols.values())

        # Formatar datas
        df_display['Data'] = pd.to_datetime(df_display['Data'], errors='coerce').dt.strftime('%d/%m/%Y')
        df_display['Entrada'] = df_display['Entrada'].apply(
            lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x) if x else ''
        )
        df_display['Saida'] = df_display['Saida'].apply(
            lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x) if x else ''
        )

        # Highlight noturno
        def highlight_noturno(row):
            if row.get('H.Noturnas', 0) > 0:
                return ['background-color: #e8eaf6'] * len(row)
            return [''] * len(row)

        st.dataframe(
            df_display.style.apply(highlight_noturno, axis=1).format({
                'Horas': '{:.2f}',
                'H.Noturnas': '{:.2f}',
                'Salario': 'R$ {:.2f}',
                'Ad.Not.20%': 'R$ {:.2f}',
                'DSR': 'R$ {:.2f}',
                'Ferias': 'R$ {:.2f}',
                'Ad.Ferias': 'R$ {:.2f}',
                '13o': 'R$ {:.2f}',
                'INSS': 'R$ {:.2f}',
                'INSS 13o': 'R$ {:.2f}',
                'Sal.Liquido': 'R$ {:.2f}',
                'Aj.Custo': 'R$ {:.2f}',
                'Total': 'R$ {:.2f}',
            }),
            use_container_width=True,
            hide_index=True,
            height=600,
        )

    with tab_resumo:
        st.subheader("Resumo por Funcionario")
        summary = get_summary_by_employee(df)

        if not summary.empty:
            summary_display = summary.rename(columns={
                'nome': 'Nome',
                'qtd_turnos': 'Turnos',
                'horas_trab_num': 'Horas',
                'horas_not_num': 'H.Noturnas',
                'salario': 'Salario',
                'ad_noturno_valor': 'Ad.Not.',
                'dsr': 'DSR',
                'ferias': 'Ferias',
                'adic_ferias': 'Ad.Ferias',
                'decimo': '13o',
                'inss': 'INSS',
                'inss_13': 'INSS 13o',
                'sal_liquido': 'Sal.Liquido',
                'ajuda_custo': 'Aj.Custo',
                'total_pagar': 'Total',
            })

            # Selecionar colunas para exibir
            cols_show = ['Nome', 'Turnos', 'Horas', 'H.Noturnas', 'Salario',
                         'Ad.Not.', 'DSR', 'Ferias', 'Ad.Ferias', '13o',
                         'INSS', 'INSS 13o', 'Sal.Liquido', 'Aj.Custo', 'Total']
            summary_show = summary_display[[c for c in cols_show if c in summary_display.columns]]

            st.dataframe(
                summary_show.style.format({
                    'Horas': '{:.2f}',
                    'H.Noturnas': '{:.2f}',
                    'Salario': 'R$ {:.2f}',
                    'Ad.Not.': 'R$ {:.2f}',
                    'DSR': 'R$ {:.2f}',
                    'Ferias': 'R$ {:.2f}',
                    'Ad.Ferias': 'R$ {:.2f}',
                    '13o': 'R$ {:.2f}',
                    'INSS': 'R$ {:.2f}',
                    'INSS 13o': 'R$ {:.2f}',
                    'Sal.Liquido': 'R$ {:.2f}',
                    'Aj.Custo': 'R$ {:.2f}',
                    'Total': 'R$ {:.2f}',
                }),
                use_container_width=True,
                hide_index=True,
            )

            # Totais
            st.divider()
            tc1, tc2, tc3 = st.columns(3)
            with tc1:
                st.metric("Total Bruto (Proventos)", format_br_currency(
                    summary['salario'].sum() + summary['ad_noturno_valor'].sum() +
                    summary['dsr'].sum() + summary['ferias'].sum() +
                    summary['adic_ferias'].sum() + summary['decimo'].sum()
                ))
            with tc2:
                st.metric("Total Descontos (INSS+VT)", format_br_currency(
                    summary['inss'].sum() + summary['inss_13'].sum() + summary['desc_vt'].sum()
                ))
            with tc3:
                st.metric("Total Liquido a Pagar", format_br_currency(summary['total_pagar'].sum()))

    with tab_download:
        st.subheader("Download da Planilha")
        st.markdown("""
A planilha Excel sera gerada no formato padrao do DP com:
- **Row 1**: Totais (SUBTOTAL)
- **Row 2**: Parametros utilizados
- **Row 3**: Headers
- **Rows 4+**: Dados com todos os calculos

Formatacao profissional com cores, bordas e colunas ajustadas.
        """)

        try:
            excel_bytes = export_payroll_excel(df, params)
            st.download_button(
                label="Baixar Planilha de Folha (.xlsx)",
                data=excel_bytes,
                file_name=f"SF_SELECAO_ESTAPAR_RJ_{pd.Timestamp.now().strftime('%d.%m.%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Erro ao gerar planilha: {e}")


st.set_page_config(
    page_title="SF Selecao - Gestao de Folha",
    page_icon="\U0001F4CA",
    layout="wide",
)

# Seletor de modulo
modulo = st.sidebar.radio(
    "Modulo",
    ["Verificacao de Folha", "Preparo Contabilidade"],
    index=0,
)

if modulo == "Preparo Contabilidade":
    _render_preparo_contabilidade()
    st.stop()

st.title("Verificacao de Folha de Pagamento")
st.markdown("**SF Servicos Selecao e Agenciamento LTDA** - Comparacao Folha de Ponto vs Folha de Pagamento")

# --- Sidebar: Upload de arquivos e configuracoes ---
with st.sidebar:
    st.header("Upload de Arquivos")

    st.subheader("1. Folha de Ponto")
    xlsx_file = st.file_uploader(
        "Arquivo Excel (.xlsx)",
        type=['xlsx'],
        help="Arquivo de medicao/folha de ponto com os turnos trabalhados"
    )

    st.subheader("2. Folha de Pagamento")
    pdf_file = st.file_uploader(
        "Arquivo PDF (.pdf)",
        type=['pdf'],
        help="Folha de pagamento processada pelo DP"
    )

    st.divider()

    # Tolerancias configuraveis (Fase 3)
    with st.expander("Configuracoes de Tolerancia"):
        hour_tolerance = st.slider(
            "Tolerancia Horas (min)",
            min_value=0, max_value=120, value=30, step=5,
            help="Tolerancia em minutos para diferenca de horas"
        )
        money_tolerance = st.slider(
            "Tolerancia Monetaria (R$)",
            min_value=0.0, max_value=50.0, value=1.0, step=0.50,
            help="Tolerancia em reais para diferencas monetarias"
        )
        h_tol = hour_tolerance / 60.0  # Converter minutos para horas
        m_tol = money_tolerance

    st.divider()

    if xlsx_file and pdf_file:
        process_btn = st.button(
            "Processar Comparacao",
            type="primary",
            use_container_width=True,
        )
    else:
        st.info("Faca upload dos dois arquivos para iniciar a comparacao.")
        process_btn = False


def _render_employee_detail(comp):
    """Renderiza detalhe de um funcionario."""
    excel = comp.excel_data or {}
    pdf = comp.pdf_data or {}

    status_colors = {
        'OK': ':green[OK]',
        'DIVERGENTE': ':red[DIVERGENTE]',
        'AUSENTE_FOLHA': ':orange[AUSENTE NA FOLHA]',
        'AUSENTE_PONTO': ':orange[AUSENTE NO PONTO]',
    }
    st.markdown(f"**Status**: {status_colors.get(comp.status, comp.status)}")

    if comp.match_confidence and comp.match_confidence < 1.0:
        st.warning(f"Matching de nome com confianca de {comp.match_confidence:.0%} (possivel variacao de grafia)")

    # Tabela comparativa (expandida com novos campos - Fase 1)
    fields = [
        ('Horas Trabalhadas', 'total_horas', 'salario_base_horas', 'h'),
        ('Salario Base (R$)', 'total_salario_base', 'salario_base_valor', 'R$'),
        ('Horas Noturnas', 'total_noturno_horas', 'noturno_horas', 'h'),
        ('Adic. Noturno (R$)', 'total_ad_noturno', 'noturno_valor', 'R$'),
        ('DSR (R$)', 'total_dsr', 'dsr', 'R$'),
        ('Ajuda de Custo (R$)', 'total_ajuda_custo', 'ajuda_custo', 'R$'),
        ('Repouso Remunerado (R$)', '_calc_repouso', 'repouso', 'R$'),
        ('Ferias Intermitente (R$)', '_calc_ferias', 'ferias', 'R$'),
        ('13o Salario (R$)', '_calc_decimo', 'decimo', 'R$'),
        ('INSS Folha (R$)', '_calc_inss_folha', 'inss_folha', 'R$'),
        ('INSS 13o (R$)', '_calc_inss_13', 'inss_13', 'R$'),
        ('Total Liquido (R$)', 'total_a_pagar', 'total_liquido', 'R$'),
    ]

    detail_rows = []
    for label, excel_key, pdf_key, unit in fields:
        e_val = excel.get(excel_key, 0)
        p_val = pdf.get(pdf_key, 0)
        diff = e_val - p_val

        if unit == 'R$':
            e_str = format_br_currency(e_val)
            p_str = format_br_currency(p_val)
            d_str = format_br_currency(diff) if abs(diff) > 0.01 else '-'
        else:
            e_str = f"{e_val:.2f}h"
            p_str = f"{p_val:.2f}h"
            d_str = f"{diff:+.2f}h" if abs(diff) > 0.01 else '-'

        status = "OK" if abs(diff) <= 1.0 else "DIVERGENTE"
        detail_rows.append({
            'Campo': label,
            'Ponto/Calculado': e_str,
            'Folha': p_str,
            'Diferenca': d_str,
            'Status': status,
        })

    detail_df = pd.DataFrame(detail_rows)

    def highlight_detail(row):
        if row['Status'] == 'DIVERGENTE':
            return ['background-color: #ffcccc'] * len(row)
        return ['background-color: #ccffcc'] * len(row)

    st.dataframe(
        detail_df.style.apply(highlight_detail, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # Turnos individuais com Tipo Dia (Fase 2)
    turnos = excel.get('turnos', [])
    if turnos:
        st.markdown("**Turnos registrados no ponto:**")
        turno_rows = []
        for t in turnos:
            date_info = classify_shift_date(t.get('data', ''))
            turno_rows.append({
                'Data': t.get('data', ''),
                'Tipo Dia': date_info['tipo'],
                'Local': t.get('evento', ''),
                'Inicio': t.get('horario_inicial', '').strftime('%H:%M') if hasattr(t.get('horario_inicial', ''), 'strftime') else str(t.get('horario_inicial', '')),
                'Fim': t.get('horario_final', '').strftime('%H:%M') if hasattr(t.get('horario_final', ''), 'strftime') else str(t.get('horario_final', '')),
                'Horas': f"{t.get('horas_trabalhadas', 0):.1f}h",
                'Noturno': f"{t.get('noturno_horas', 0):.1f}h" if t.get('noturno_horas', 0) > 0 else '-',
                'Ajuda': format_br_currency(t.get('ajuda_custo', 0)),
            })

        turno_df = pd.DataFrame(turno_rows)

        def highlight_tipo_dia(row):
            if row.get('Tipo Dia') == 'FERIADO':
                return ['background-color: #ffcccc'] * len(row)
            elif row.get('Tipo Dia') == 'DOMINGO':
                return ['background-color: #ffe0b2'] * len(row)
            elif row.get('Tipo Dia') == 'SABADO':
                return ['background-color: #fff9c4'] * len(row)
            return [''] * len(row)

        st.dataframe(
            turno_df.style.apply(highlight_tipo_dia, axis=1),
            use_container_width=True,
            hide_index=True,
        )

    # Divergencias
    if comp.divergences:
        st.markdown("**Divergencias encontradas:**")
        for div in comp.divergences:
            if div.severity == 'CRITICO':
                icon = "\U0001F534"
            elif div.severity == 'ALERTA':
                icon = "\U0001F7E1"
            else:
                icon = "\U0001F535"
            st.markdown(f"{icon} **{div.field}**: {div.description}")


# --- Processamento ---
if xlsx_file and pdf_file and process_btn:
    with st.spinner("Processando arquivos..."):
        # Parse Excel
        try:
            excel_data = parse_folha_de_ponto(xlsx_file.read())
            xlsx_file.seek(0)
        except Exception as e:
            st.error(f"Erro ao processar folha de ponto: {e}")
            st.stop()

        # Parse PDF
        try:
            pdf_data = parse_folha_de_pagamento(pdf_file.read())
            pdf_file.seek(0)
        except Exception as e:
            st.error(f"Erro ao processar folha de pagamento: {e}")
            st.stop()

        # Carregar correcoes manuais de nomes (Fase 5)
        try:
            corrections = get_name_corrections()
        except Exception:
            corrections = {}

        # Comparar com tolerancias configuraveis
        report = compare_payrolls(excel_data, pdf_data,
                                  hour_tolerance=h_tol,
                                  money_tolerance=m_tol,
                                  corrections=corrections)

    # Salvar no session_state
    st.session_state['report'] = report
    st.session_state['excel_data'] = excel_data
    st.session_state['pdf_data'] = pdf_data

    # Auto-salvar no historico (Fase 4)
    try:
        xlsx_name = xlsx_file.name if xlsx_file else ''
        pdf_name = pdf_file.name if pdf_file else ''
        comp_id = save_comparison(report, xlsx_name, pdf_name)
        st.session_state['last_comparison_id'] = comp_id
    except Exception:
        pass  # Nao bloquear se o banco falhar


# --- Exibir resultados ---
if 'report' in st.session_state:
    report = st.session_state['report']
    excel_data = st.session_state['excel_data']
    pdf_data = st.session_state['pdf_data']

    # --- Metricas ---
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Funcionarios no Ponto", report.total_excel_employees)
    with col2:
        st.metric("Funcionarios na Folha", report.total_pdf_employees)
    with col3:
        st.metric(
            "Matched",
            report.total_matched,
            delta=f"-{report.total_excel_employees - report.total_matched} ausentes" if report.total_excel_employees > report.total_matched else None,
            delta_color="inverse"
        )
    with col4:
        st.metric(
            "OK",
            report.total_ok,
            delta_color="normal"
        )
    with col5:
        st.metric(
            "Divergentes",
            report.total_divergent,
            delta_color="inverse"
        )

    st.divider()

    # --- Abas (com Historico adicionado - Fase 4) ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Resumo",
        "Comparacao Detalhada",
        "Funcionarios Ausentes",
        "Alertas",
        "Download Relatorio",
        "Historico",
    ])

    # === TAB 1: RESUMO com graficos Plotly (Fase 3) ===
    with tab1:
        st.subheader("Resumo da Comparacao")

        total = report.total_matched + len(report.excel_only) + len(report.pdf_only)
        if total > 0:
            col_a, col_b = st.columns(2)

            with col_a:
                # Grafico de pizza (donut) - Distribuicao de Status
                status_labels = ['OK', 'Divergente', 'Ausente na Folha', 'Ausente no Ponto']
                status_values = [
                    report.total_ok,
                    report.total_divergent,
                    len(report.excel_only),
                    len(report.pdf_only),
                ]
                status_colors_chart = ['#27ae60', '#e74c3c', '#f39c12', '#3498db']

                # Filtrar zeros
                filtered = [(l, v, c) for l, v, c in zip(status_labels, status_values, status_colors_chart) if v > 0]
                if filtered:
                    labels, values, colors = zip(*filtered)
                    fig_pie = go.Figure(data=[go.Pie(
                        labels=labels, values=values,
                        hole=0.4,
                        marker=dict(colors=colors),
                        textinfo='label+value',
                        textposition='outside',
                    )])
                    fig_pie.update_layout(
                        title="Distribuicao de Status",
                        showlegend=True,
                        height=350,
                        margin=dict(t=50, b=20, l=20, r=20),
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)

            with col_b:
                # Grafico de barras - Divergencias por tipo
                div_df = generate_divergence_detail(report)
                if not div_df.empty:
                    type_counts = div_df['Campo'].value_counts().reset_index()
                    type_counts.columns = ['Tipo', 'Quantidade']

                    fig_bar = px.bar(
                        type_counts, x='Tipo', y='Quantidade',
                        title="Divergencias por Tipo",
                        color='Quantidade',
                        color_continuous_scale='Reds',
                    )
                    fig_bar.update_layout(
                        height=350,
                        margin=dict(t=50, b=20, l=20, r=20),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.success("Nenhuma divergencia encontrada!")

            # Grafico de barras - Diferenca salarial por funcionario (apenas divergentes)
            divergent_comps = [c for c in report.comparisons if c.status == 'DIVERGENTE']
            if divergent_comps:
                st.markdown("### Diferenca Salarial por Funcionario (Divergentes)")
                names = []
                diffs = []
                for c in divergent_comps:
                    excel = c.excel_data or {}
                    pdf = c.pdf_data or {}
                    nome = c.nome_excel or c.nome_pdf
                    diff = excel.get('total_salario_base', 0) - pdf.get('salario_base_valor', 0)
                    names.append(nome)
                    diffs.append(diff)

                fig_diff = go.Figure(data=[go.Bar(
                    x=names, y=diffs,
                    marker_color=['#e74c3c' if d > 0 else '#3498db' for d in diffs],
                )])
                fig_diff.update_layout(
                    yaxis_title="Diferenca (R$)",
                    height=300,
                    margin=dict(t=30, b=20, l=20, r=20),
                )
                st.plotly_chart(fig_diff, use_container_width=True)

        # Divergencias criticas
        div_df = generate_divergence_detail(report)
        critical = div_df[div_df['Severidade'] == 'CRITICO'] if not div_df.empty else pd.DataFrame()
        if not critical.empty:
            st.markdown("### Divergencias Criticas")
            st.dataframe(
                critical[['Funcionario', 'Campo', 'Valor Ponto', 'Valor Folha', 'Diferenca', 'Descricao']],
                use_container_width=True,
                hide_index=True,
            )

    # === TAB 2: COMPARACAO DETALHADA ===
    with tab2:
        st.subheader("Comparacao Detalhada por Funcionario")

        comp_df = generate_comparison_dataframe(report)

        # Filtro de status
        status_filter = st.multiselect(
            "Filtrar por Status:",
            options=comp_df['Status'].unique().tolist() if not comp_df.empty else [],
            default=comp_df['Status'].unique().tolist() if not comp_df.empty else [],
        )

        if not comp_df.empty and status_filter:
            filtered = comp_df[comp_df['Status'].isin(status_filter)]

            def highlight_status(row):
                if row['Status'] == 'DIVERGENTE':
                    return ['background-color: #ffcccc'] * len(row)
                elif row['Status'] == 'OK':
                    return ['background-color: #ccffcc'] * len(row)
                elif 'AUSENTE' in row['Status']:
                    return ['background-color: #ffffcc'] * len(row)
                return [''] * len(row)

            styled = filtered.style.apply(highlight_status, axis=1)
            st.dataframe(styled, use_container_width=True, hide_index=True, height=600)

        # Detalhe por funcionario
        st.markdown("---")
        st.subheader("Detalhe Individual")
        emp_names = [c.nome_excel or c.nome_pdf for c in report.comparisons]
        selected_emp = st.selectbox("Selecione um funcionario:", sorted(emp_names))

        if selected_emp:
            comp = next(
                (c for c in report.comparisons if (c.nome_excel == selected_emp or c.nome_pdf == selected_emp)),
                None
            )
            if comp:
                _render_employee_detail(comp)

    # === TAB 3: FUNCIONARIOS AUSENTES com correcao manual (Fase 5) ===
    with tab3:
        st.subheader("Funcionarios Ausentes")

        missing_folha, missing_ponto = generate_missing_employees_df(report)

        if not missing_folha.empty:
            st.markdown("### Presentes no Ponto, Ausentes na Folha de Pagamento")
            st.warning(f"{len(missing_folha)} funcionario(s) trabalharam mas NAO constam na folha de pagamento!")
            st.dataframe(missing_folha, use_container_width=True, hide_index=True)
        else:
            st.success("Todos os funcionarios do ponto constam na folha.")

        st.divider()

        if not missing_ponto.empty:
            st.markdown("### Presentes na Folha, Ausentes no Ponto")
            st.warning(f"{len(missing_ponto)} funcionario(s) na folha mas NAO constam no ponto!")
            st.dataframe(missing_ponto, use_container_width=True, hide_index=True)
        else:
            st.success("Todos os funcionarios da folha constam no ponto.")

        # Correcao manual de nomes (Fase 5)
        if not missing_folha.empty or not missing_ponto.empty:
            st.divider()
            st.markdown("### Correcao Manual de Nomes")
            st.caption("Se um funcionario aparece como ausente devido a diferenca de grafia entre Ponto e Folha, vincule os nomes abaixo.")

            excel_only_names = report.excel_only if report.excel_only else []
            pdf_only_names = report.pdf_only if report.pdf_only else []

            if excel_only_names and pdf_only_names:
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    nome_excel_sel = st.selectbox("Nome no Ponto (Excel):", excel_only_names, key='corr_excel')
                with col_c2:
                    nome_pdf_sel = st.selectbox("Nome na Folha (PDF):", pdf_only_names, key='corr_pdf')

                if st.button("Salvar Vinculo", type="primary"):
                    try:
                        save_name_correction(nome_excel_sel, nome_pdf_sel)
                        st.success(f"Vinculo salvo: '{nome_excel_sel}' = '{nome_pdf_sel}'. Re-processe para aplicar.")
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")

            # Mostrar correcoes salvas
            try:
                saved_corrections = get_name_corrections()
                if saved_corrections:
                    st.markdown("**Vinculos salvos:**")
                    corr_rows = [{'Ponto': k, 'Folha': v} for k, v in saved_corrections.items()]
                    st.dataframe(pd.DataFrame(corr_rows), use_container_width=True, hide_index=True)

                    del_name = st.selectbox("Remover vinculo:", list(saved_corrections.keys()), key='del_corr')
                    if st.button("Remover"):
                        delete_name_correction(del_name)
                        st.success(f"Vinculo removido: '{del_name}'")
                        st.rerun()
            except Exception:
                pass

    # === TAB 4: ALERTAS ===
    with tab4:
        st.subheader("Alertas de Validacao")

        alerts_df = generate_alerts_df(report)

        if not alerts_df.empty:
            # Filtro por severidade
            sev_filter = st.multiselect(
                "Filtrar por Severidade:",
                options=alerts_df['Severidade'].unique().tolist(),
                default=alerts_df['Severidade'].unique().tolist(),
                key='sev_filter',
            )
            filtered_alerts = alerts_df[alerts_df['Severidade'].isin(sev_filter)] if sev_filter else alerts_df

            def highlight_severity(row):
                if row['Severidade'] == 'ALTA':
                    return ['background-color: #ffcccc'] * len(row)
                elif row['Severidade'] == 'MEDIA':
                    return ['background-color: #ffffcc'] * len(row)
                return [''] * len(row)

            styled_alerts = filtered_alerts.style.apply(highlight_severity, axis=1)
            st.dataframe(styled_alerts, use_container_width=True, hide_index=True)

            st.caption(f"Total: {len(filtered_alerts)} alerta(s)")
        else:
            st.success("Nenhum alerta de validacao encontrado.")

    # === TAB 5: DOWNLOAD ===
    with tab5:
        st.subheader("Download do Relatorio")

        st.markdown("""
O relatorio Excel contem as seguintes planilhas:
- **Resumo**: Metricas gerais da comparacao
- **Comparacao Detalhada**: Tabela completa com valores do ponto vs folha (incluindo Repouso, Ferias, 13o, INSS)
- **Divergencias**: Lista detalhada de todas as divergencias encontradas
- **Ausentes na Folha**: Funcionarios que trabalharam mas nao estao na folha
- **Alertas**: Alertas de validacao (jornadas irregulares, feriados, dias consecutivos, etc.)
        """)

        col_dl1, col_dl2 = st.columns(2)

        with col_dl1:
            excel_bytes = generate_excel_report(report)
            st.download_button(
                label="Baixar Relatorio Excel",
                data=excel_bytes,
                file_name="relatorio_verificacao_folha.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )

        with col_dl2:
            try:
                pdf_bytes = generate_pdf_report(report)
                st.download_button(
                    label="Baixar Relatorio PDF",
                    data=pdf_bytes,
                    file_name="relatorio_verificacao_folha.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.warning(f"Erro ao gerar PDF: {e}")

    # === TAB 6: HISTORICO (Fase 4) ===
    with tab6:
        st.subheader("Historico de Comparacoes")

        try:
            history = get_comparison_history(limit=20)
            if history:
                hist_rows = []
                for h in history:
                    hist_rows.append({
                        'Data': h['created_at'],
                        'Excel': h.get('excel_filename', '-'),
                        'PDF': h.get('pdf_filename', '-'),
                        'Ponto': h['total_excel_employees'],
                        'Folha': h['total_pdf_employees'],
                        'OK': h['total_ok'],
                        'Divergentes': h['total_divergent'],
                        'Aus. Folha': h.get('total_excel_only', 0),
                        'Aus. Ponto': h.get('total_pdf_only', 0),
                    })
                st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)

                # Grafico de tendencia
                if len(history) > 1:
                    st.markdown("### Tendencia de Divergencias")
                    trend_data = pd.DataFrame(hist_rows)
                    fig_trend = go.Figure()
                    fig_trend.add_trace(go.Scatter(
                        x=trend_data['Data'], y=trend_data['OK'],
                        mode='lines+markers', name='OK',
                        line=dict(color='#27ae60'),
                    ))
                    fig_trend.add_trace(go.Scatter(
                        x=trend_data['Data'], y=trend_data['Divergentes'],
                        mode='lines+markers', name='Divergentes',
                        line=dict(color='#e74c3c'),
                    ))
                    fig_trend.update_layout(
                        height=300,
                        margin=dict(t=30, b=20, l=20, r=20),
                        xaxis_title="Data",
                        yaxis_title="Quantidade",
                    )
                    st.plotly_chart(fig_trend, use_container_width=True)

                # Busca de tendencia por funcionario
                st.markdown("### Tendencia por Funcionario")
                emp_search = st.text_input("Buscar funcionario:", key='trend_search')
                if emp_search and len(emp_search) >= 3:
                    trend = get_employee_trend(emp_search)
                    if trend:
                        trend_rows = []
                        for t in trend:
                            trend_rows.append({
                                'Data': t['created_at'],
                                'Nome Excel': t.get('nome_excel', '-'),
                                'Nome PDF': t.get('nome_pdf', '-'),
                                'Status': t['status'],
                            })
                        st.dataframe(pd.DataFrame(trend_rows), use_container_width=True, hide_index=True)
                    else:
                        st.info("Nenhum resultado encontrado.")
            else:
                st.info("Nenhuma comparacao salva ainda. Processe arquivos para criar o historico.")
        except Exception as e:
            st.warning(f"Erro ao carregar historico: {e}")

else:
    # Estado inicial
    st.info("Faca upload da **Folha de Ponto** (Excel) e da **Folha de Pagamento** (PDF) na barra lateral e clique em **Processar Comparacao**.")

    st.markdown("""
### Como usar:

1. Na barra lateral, faca upload da **Folha de Ponto** (arquivo .xlsx com as medicoes/turnos)
2. Faca upload da **Folha de Pagamento** (arquivo .pdf processado pelo DP)
3. Configure as tolerancias desejadas (opcional)
4. Clique em **Processar Comparacao**
5. Analise os resultados nas abas: Resumo, Comparacao Detalhada, Ausentes, Alertas, Historico
6. Baixe o relatorio Excel ou PDF completo na aba Download

### Regras de Verificacao:
- **Horas Trabalhadas**: Total de horas do ponto vs salario base da folha
- **Adicional Noturno**: Horas na janela 22h-05h com adicional de 20%
- **DSR**: Descanso semanal remunerado (proporcional ao salario base)
- **Repouso Remunerado**: Adicional Noturno / 6
- **Ferias Intermitente**: (Base + Noturno + DSR + Repouso) / 12 * 4/3
- **13o Salario**: (Base + Noturno + DSR + Repouso) / 12
- **INSS**: Aliquotas progressivas (tabela 2025)
- **Ajuda de Custo**: Valores de transporte/alimentacao
- **Feriados/Domingos**: Alertas para trabalho em dias especiais
- **Dias Consecutivos**: Alerta para mais de 6 dias seguidos
- **Funcionarios Ausentes**: Quem trabalhou mas nao consta na folha (e vice-versa)
    """)
