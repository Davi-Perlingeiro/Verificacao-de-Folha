import re
import unicodedata
from difflib import SequenceMatcher


def normalize_name(name: str) -> str:
    """Normaliza nome: remove acentos, uppercase, colapsa espacos."""
    if not name:
        return ""
    # Remove acentos via decomposicao NFD
    nfkd = unicodedata.normalize('NFKD', str(name))
    ascii_only = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    # Uppercase e colapsa espacos
    result = re.sub(r'\s+', ' ', ascii_only.upper().strip())
    return result


def match_employees(excel_names: list, pdf_names: list, corrections: dict = None) -> dict:
    """
    Faz matching entre nomes do Excel e do PDF.
    corrections: dict opcional {nome_excel: nome_pdf} para correcoes manuais salvas.
    Retorna:
        matched: lista de (nome_excel, nome_pdf, nome_normalizado, confianca)
        excel_only: nomes que estao no Excel mas nao no PDF
        pdf_only: nomes que estao no PDF mas nao no Excel
    """
    corrections = corrections or {}

    excel_norm = {}
    for n in excel_names:
        key = normalize_name(n)
        if key:
            excel_norm[key] = n

    pdf_norm = {}
    for n in pdf_names:
        key = normalize_name(n)
        if key:
            pdf_norm[key] = n

    matched = []
    excel_unmatched = set(excel_norm.keys())
    pdf_unmatched = set(pdf_norm.keys())

    # Fase 0: Aplicar correcoes manuais salvas
    for corr_excel, corr_pdf in corrections.items():
        e_key = normalize_name(corr_excel)
        p_key = normalize_name(corr_pdf)
        if e_key in excel_unmatched and p_key in pdf_unmatched:
            matched.append((excel_norm[e_key], pdf_norm[p_key], e_key, 1.0))
            excel_unmatched.discard(e_key)
            pdf_unmatched.discard(p_key)

    # Fase 1: match exato normalizado
    for key in list(excel_unmatched):
        if key in pdf_unmatched:
            matched.append((excel_norm[key], pdf_norm[key], key, 1.0))
            excel_unmatched.discard(key)
            pdf_unmatched.discard(key)

    # Fase 2: fuzzy match para variacoes (Sousa vs Souza, etc.)
    for e_key in list(excel_unmatched):
        best_match = None
        best_ratio = 0.0
        for p_key in pdf_unmatched:
            ratio = SequenceMatcher(None, e_key, p_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = p_key
        if best_match and best_ratio >= 0.85:
            matched.append((
                excel_norm[e_key],
                pdf_norm[best_match],
                e_key,
                best_ratio
            ))
            excel_unmatched.discard(e_key)
            pdf_unmatched.discard(best_match)

    return {
        'matched': matched,
        'excel_only': [excel_norm[k] for k in sorted(excel_unmatched)],
        'pdf_only': [pdf_norm[k] for k in sorted(pdf_unmatched)],
    }
