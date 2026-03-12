import io
import re
import PyPDF2
from utils.formatting import parse_br_number, parse_pdf_hours


# Patterns com fallbacks para cada campo do PDF
PATTERNS = {
    'header': [
        r'^(\d{6})\s+([A-Z][A-Z\s]+?)\s+(\d+,\d{2})\s+\d+\s+\d+',
        r'^(\d{4,6})\s+([A-Z][A-Z\s]{5,}?)\s+(\d+[,\.]\d{2})',
    ],
    'funcao': [
        r'Fun..o\s*:(.+?)$',
        r'Cargo\s*:(.+?)$',
        r'Fun[cç][aã]o\s*:(.+?)$',
    ],
    'salario_base': [
        r'Sal.rio Base\s+([\d.,]+)\s+(\d{3}:\d{2})\s+001',
        r'Sal.rio Base\s+([\d.,]+)\s+(\d{2,3}:\d{2})',
        r'Sal.rio\s+Base\s+([\d.,]+)',
    ],
    'noturno': [
        r'Noturno Sobre Horas Trabalhadas\s+([\d.,]+)\s+(\d{3}:\d{2})\s+035',
        r'Noturno.*?Trabalhadas\s+([\d.,]+)\s+(\d{2,3}:\d{2})',
        r'Ad\.?\s*Noturno\s+([\d.,]+)\s+(\d{2,3}:\d{2})',
    ],
    'dsr': [
        r'DSR Horista/intermitente\s+([\d.,]+)\s+248',
        r'DSR.*?intermitente\s+([\d.,]+)',
        r'DSR.*?Horista\s+([\d.,]+)',
        r'DSR\s+([\d.,]+)',
    ],
    'ajuda_custo': [
        r'Ajuda de Custo\s+([\d.,]+)\s+422',
        r'Ajuda\s+de\s+Custo\s+([\d.,]+)',
        r'Aux.*?Transporte\s+([\d.,]+)',
    ],
    'repouso': [
        r'Repouso Remunerado\s+([\d.,]+)\s+420',
        r'Repouso\s+Remunerado\s+([\d.,]+)',
        r'Rep\.?\s*Remunerado\s+([\d.,]+)',
    ],
    'ferias': [
        r'F.rias.*?Intermitente\s+([\d.,]+)\s+274',
        r'F[eé]rias.*?Intermitente\s+([\d.,]+)',
        r'F.rias\s*\+\s*1/3\s+([\d.,]+)',
    ],
    'decimo': [
        r'D.cimo Terceiro.*?Intermitente\s+([\d.,]+)\s+273',
        r'D[eé]cimo\s+Terceiro.*?Intermitente\s+([\d.,]+)',
        r'D.cimo\s+Terceiro\s+([\d.,]+)',
    ],
    'inss_13': [
        r'INSS 13.*?Intermitente\s+([\d.,]+)\s+897',
        r'INSS\s+13.*?Intermitente\s+([\d.,]+)',
        r'INSS.*?13.*?Sal\s+([\d.,]+)',
    ],
    'inss_folha': [
        r'INSS Folha\s+([\d.,]+)\s+903',
        r'INSS\s+Folha\s+([\d.,]+)',
        r'INSS\s+([\d.,]+)\s+903',
    ],
    'totais': [
        r'____/____/______([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)',
        r'_{4,}/_{4,}/_{4,}([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)',
        r'Total\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$',
    ],
}


def _try_patterns(line: str, pattern_list: list):
    """Tenta cada pattern na lista e retorna o primeiro match."""
    for pattern in pattern_list:
        m = re.search(pattern, line)
        if m:
            return m
    return None


def parse_folha_de_pagamento(file_bytes) -> dict:
    """
    Faz parse da folha de pagamento PDF.
    Retorna dict com chave = nome do funcionario (UPPERCASE do PDF),
    valor = dict com todos os campos extraidos.
    """
    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    # Separar em blocos por header de funcionario (mais robusto que ***)
    header_pattern = re.compile(
        r'^(\d{4,6})\s+([A-Z][A-Z\s]+?)\s+(\d+[,\.]\d{2})\s+\d+\s+\d+',
        re.MULTILINE
    )
    headers = list(header_pattern.finditer(full_text))

    employees = {}

    for i, hdr in enumerate(headers):
        start = hdr.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(full_text)
        block = full_text[start:end]
        emp = _parse_employee_block(block)
        if emp and emp.get('nome'):
            employees[emp['nome']] = emp

    # Extrair resumo da ultima pagina
    last_page_text = reader.pages[-1].extract_text() or ""
    summary = _parse_summary(last_page_text)

    return {
        'employees': employees,
        'summary': summary,
    }


def _parse_employee_block(block: str) -> dict:
    """Faz parse de um bloco individual de funcionario."""
    lines = block.strip().split('\n')
    emp = {
        'code': '',
        'nome': '',
        'salario_hora': 0.0,
        'funcao': '',
        'salario_base_valor': 0.0,
        'salario_base_horas': 0.0,
        'noturno_valor': 0.0,
        'noturno_horas': 0.0,
        'dsr': 0.0,
        'ajuda_custo': 0.0,
        'repouso': 0.0,
        'ferias': 0.0,
        'decimo': 0.0,
        'inss_13': 0.0,
        'inss_folha': 0.0,
        'total_adicionais': 0.0,
        'total_descontos': 0.0,
        'total_liquido': 0.0,
    }

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 1. Header do funcionario
        m = _try_patterns(line, PATTERNS['header'])
        if m:
            emp['code'] = m.group(1)
            emp['nome'] = m.group(2).strip()
            emp['salario_hora'] = parse_br_number(m.group(3))
            continue

        # 2. Funcao
        m = _try_patterns(line, PATTERNS['funcao'])
        if m:
            emp['funcao'] = m.group(1).strip()
            continue

        # 3. Salario Base
        m = _try_patterns(line, PATTERNS['salario_base'])
        if m:
            emp['salario_base_valor'] = parse_br_number(m.group(1))
            if m.lastindex >= 2:
                emp['salario_base_horas'] = parse_pdf_hours(m.group(2))
            continue

        # 4. Noturno
        m = _try_patterns(line, PATTERNS['noturno'])
        if m:
            emp['noturno_valor'] = parse_br_number(m.group(1))
            if m.lastindex >= 2:
                emp['noturno_horas'] = parse_pdf_hours(m.group(2))
            continue

        # 5. DSR
        m = _try_patterns(line, PATTERNS['dsr'])
        if m:
            emp['dsr'] = parse_br_number(m.group(1))
            continue

        # 6. Ajuda de Custo
        m = _try_patterns(line, PATTERNS['ajuda_custo'])
        if m:
            emp['ajuda_custo'] = parse_br_number(m.group(1))
            continue

        # 7. Repouso Remunerado
        m = _try_patterns(line, PATTERNS['repouso'])
        if m:
            emp['repouso'] = parse_br_number(m.group(1))
            continue

        # 8. Ferias
        m = _try_patterns(line, PATTERNS['ferias'])
        if m:
            emp['ferias'] = parse_br_number(m.group(1))
            continue

        # 9. Decimo Terceiro
        m = _try_patterns(line, PATTERNS['decimo'])
        if m:
            emp['decimo'] = parse_br_number(m.group(1))
            continue

        # 10. INSS 13o Salario
        m = _try_patterns(line, PATTERNS['inss_13'])
        if m:
            emp['inss_13'] = parse_br_number(m.group(1))
            continue

        # 11. INSS Folha
        m = _try_patterns(line, PATTERNS['inss_folha'])
        if m:
            emp['inss_folha'] = parse_br_number(m.group(1))
            continue

        # 12. Linha de totais
        m = _try_patterns(line, PATTERNS['totais'])
        if m:
            emp['total_adicionais'] = parse_br_number(m.group(1))
            emp['total_descontos'] = parse_br_number(m.group(2))
            emp['total_liquido'] = parse_br_number(m.group(3))
            continue

    return emp if emp['nome'] else None


def _parse_summary(text: str) -> dict:
    """Extrai resumo geral da folha (ultima pagina)."""
    summary = {
        'total_geral': 0.0,
        'total_descontos': 0.0,
        'total_liquido': 0.0,
        'total_funcionarios': 0,
        'total_inss': 0.0,
        'total_fgts': 0.0,
    }

    # Total Funcionarios
    m = re.search(r'Total Funcion.rios\s*(\d+)', text)
    if m:
        summary['total_funcionarios'] = int(m.group(1))

    # Total INSS
    m = re.search(r'Total INSS\s*([\d.,]+)', text)
    if m:
        summary['total_inss'] = parse_br_number(m.group(1))

    # Total FGTS
    m = re.search(r'Total FGTS\s*([\d.,]+)', text)
    if m:
        summary['total_fgts'] = parse_br_number(m.group(1))

    return summary
