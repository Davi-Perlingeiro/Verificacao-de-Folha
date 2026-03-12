"""
Modulo de persistencia SQLite para historico de comparacoes.
Usa WAL mode para compatibilidade com OneDrive.
"""

import sqlite3
import json
import os
import datetime


DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DB_PATH = os.path.join(DB_DIR, 'historico.db')


def _get_connection() -> sqlite3.Connection:
    """Retorna conexao SQLite com WAL mode."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inicializa tabelas do banco."""
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            excel_filename TEXT,
            pdf_filename TEXT,
            total_excel_employees INTEGER DEFAULT 0,
            total_pdf_employees INTEGER DEFAULT 0,
            total_matched INTEGER DEFAULT 0,
            total_ok INTEGER DEFAULT 0,
            total_divergent INTEGER DEFAULT 0,
            total_excel_only INTEGER DEFAULT 0,
            total_pdf_only INTEGER DEFAULT 0,
            summary_json TEXT
        );

        CREATE TABLE IF NOT EXISTS employee_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comparison_id INTEGER NOT NULL,
            nome_excel TEXT,
            nome_pdf TEXT,
            status TEXT,
            match_confidence REAL,
            excel_data_json TEXT,
            pdf_data_json TEXT,
            divergences_json TEXT,
            FOREIGN KEY (comparison_id) REFERENCES comparisons(id)
        );

        CREATE TABLE IF NOT EXISTS name_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_excel TEXT NOT NULL,
            nome_pdf TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(nome_excel, nome_pdf)
        );
    """)
    conn.commit()
    conn.close()


def save_comparison(report, excel_filename: str = '', pdf_filename: str = '') -> int:
    """Salva resultado de comparacao no banco. Retorna o ID."""
    conn = _get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO comparisons
                (excel_filename, pdf_filename, total_excel_employees, total_pdf_employees,
                 total_matched, total_ok, total_divergent, total_excel_only, total_pdf_only)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            excel_filename,
            pdf_filename,
            report.total_excel_employees,
            report.total_pdf_employees,
            report.total_matched,
            report.total_ok,
            report.total_divergent,
            len(report.excel_only),
            len(report.pdf_only),
        ))
        comp_id = cursor.lastrowid

        for comp in report.comparisons:
            divergences_data = []
            for d in comp.divergences:
                divergences_data.append({
                    'field': d.field,
                    'excel_value': d.excel_value,
                    'pdf_value': d.pdf_value,
                    'difference': d.difference,
                    'severity': d.severity,
                    'description': d.description,
                })

            conn.execute("""
                INSERT INTO employee_results
                    (comparison_id, nome_excel, nome_pdf, status,
                     match_confidence, excel_data_json, pdf_data_json, divergences_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                comp_id,
                comp.nome_excel,
                comp.nome_pdf,
                comp.status,
                comp.match_confidence,
                _serialize_employee_data(comp.excel_data),
                _serialize_employee_data(comp.pdf_data),
                json.dumps(divergences_data, ensure_ascii=False),
            ))

        conn.commit()
        return comp_id
    finally:
        conn.close()


def get_comparison_history(limit: int = 20) -> list:
    """Retorna historico de comparacoes recentes."""
    conn = _get_connection()
    try:
        rows = conn.execute("""
            SELECT id, created_at, excel_filename, pdf_filename,
                   total_excel_employees, total_pdf_employees,
                   total_matched, total_ok, total_divergent,
                   total_excel_only, total_pdf_only
            FROM comparisons
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_employee_trend(nome: str, limit: int = 10) -> list:
    """Retorna tendencia de resultados para um funcionario."""
    conn = _get_connection()
    try:
        rows = conn.execute("""
            SELECT c.created_at, er.status, er.nome_excel, er.nome_pdf,
                   er.divergences_json, er.excel_data_json, er.pdf_data_json
            FROM employee_results er
            JOIN comparisons c ON er.comparison_id = c.id
            WHERE UPPER(er.nome_excel) LIKE UPPER(?) OR UPPER(er.nome_pdf) LIKE UPPER(?)
            ORDER BY c.created_at DESC
            LIMIT ?
        """, (f'%{nome}%', f'%{nome}%', limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_name_correction(nome_excel: str, nome_pdf: str):
    """Salva correcao manual de nome."""
    conn = _get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO name_corrections (nome_excel, nome_pdf)
            VALUES (?, ?)
        """, (nome_excel, nome_pdf))
        conn.commit()
    finally:
        conn.close()


def get_name_corrections() -> dict:
    """Retorna dict de correcoes de nome: {nome_excel: nome_pdf}."""
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT nome_excel, nome_pdf FROM name_corrections").fetchall()
        return {r['nome_excel']: r['nome_pdf'] for r in rows}
    finally:
        conn.close()


def delete_name_correction(nome_excel: str):
    """Remove uma correcao manual de nome."""
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM name_corrections WHERE nome_excel = ?", (nome_excel,))
        conn.commit()
    finally:
        conn.close()


def _serialize_employee_data(data) -> str:
    """Serializa dados do funcionario para JSON, tratando tipos nao-serializaveis."""
    if not data:
        return '{}'

    clean = {}
    for k, v in data.items():
        if k == 'turnos':
            # Serializar turnos sem datetimes
            turnos = []
            for t in v:
                turno = {}
                for tk, tv in t.items():
                    if isinstance(tv, (datetime.datetime, datetime.date, datetime.time)):
                        turno[tk] = str(tv)
                    else:
                        turno[tk] = tv
                turnos.append(turno)
            clean[k] = turnos
        elif isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
            clean[k] = str(v)
        else:
            clean[k] = v

    return json.dumps(clean, ensure_ascii=False)


# Inicializar banco ao importar
init_db()
