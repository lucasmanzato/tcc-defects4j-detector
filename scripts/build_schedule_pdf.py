"""Generate the TCC project schedule as a PDF.

Produces ``results/cronograma_tcc.pdf`` with: title page, executive summary,
work breakdown structure (WBS), milestones table, Gantt-style timeline, risks,
and critical path — following standard project management practice (PMBOK
lite).

Edit the ``PHASES`` and ``RISKS`` lists below to adjust scope.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Project parameters
# ---------------------------------------------------------------------------
PROJECT_TITLE = "TCC — Detecção de padrões de correção de bugs"
SUBTITLE = "Cronograma de execução até a entrega final"
AUTHOR = "Lucas Manzato Gonçalves"
START_DATE = date(2026, 5, 2)
END_DATE = date(2026, 7, 20)
GENERATED = date(2026, 5, 2)

# Work Breakdown Structure: each phase has a start, end, and list of tasks.
PHASES = [
    {
        "id": "F1",
        "name": "Fase 1 — Extensões técnicas",
        "start": date(2026, 5, 2),
        "end": date(2026, 6, 19),
        "objective": "Concluir as melhorias técnicas no detector, validar a "
                     "capacidade de generalização e consolidar a confirmação "
                     "de resultados.",
        "milestones": [
            {
                "id": "M1.1",
                "name": "Validação e expansão da bateria de testes",
                "start": date(2026, 5, 2),
                "end": date(2026, 5, 26),
                "deliverable": "Cobertura ≥ 90% no módulo `src/features.py`; "
                               "novos casos de borda documentados em "
                               "`tests/`; suite com pelo menos 80 testes "
                               "passando e relatório de cobertura anexado.",
            },
            {
                "id": "M1.2",
                "name": "Implementação de um segundo padrão",
                "start": date(2026, 5, 27),
                "end": date(2026, 6, 9),
                "deliverable": "Detecção funcional de um segundo padrão "
                               "(ex.: `wrongMethodReference` ou "
                               "`missingMethodCall`); arquitetura "
                               "generalizada para múltiplos padrões; "
                               "recall ≥ 70% no ground truth do novo padrão.",
            },
            {
                "id": "M1.3",
                "name": "Confirmação manual e LLM (estudo de todo o "
                        "resultado)",
                "start": date(2026, 6, 10),
                "end": date(2026, 6, 19),
                "deliverable": "Revisão manual de toda a saída do detector "
                               "em cada repo-alvo; integração de LLM para "
                               "confirmação automática (flag "
                               "`--llm-confirm`); estudo comparativo entre "
                               "detector estrutural, validação humana e "
                               "LLM; tabela de divergências com análise.",
            },
        ],
    },
    {
        "id": "F2",
        "name": "Fase 2 — Redação do TCC",
        "start": date(2026, 6, 20),
        "end": date(2026, 7, 8),
        "objective": "Produzir a primeira versão completa do texto, "
                     "escrevendo do concreto para o abstrato: resultados "
                     "primeiro, depois conclusão, metodologia e por fim "
                     "introdução / referencial teórico.",
        "milestones": [
            {
                "id": "M2.1",
                "name": "Capítulo de resultados e análises",
                "start": date(2026, 6, 20),
                "end": date(2026, 6, 27),
                "deliverable": "Métricas no ground truth (recall 100% / "
                               "baseline 33%); estudos de caso "
                               "(error-prone, flink, joda-time); análise "
                               "comparativa detector × manual × LLM; "
                               "discussão de falsos positivos e negativos.",
            },
            {
                "id": "M2.2",
                "name": "Capítulo de conclusão",
                "start": date(2026, 6, 28),
                "end": date(2026, 7, 1),
                "deliverable": "Síntese das contribuições, limitações "
                               "identificadas, agenda de trabalhos "
                               "futuros (extensão para demais padrões, "
                               "pipeline em produção, dashboard).",
            },
            {
                "id": "M2.3",
                "name": "Capítulo de metodologia e implementação",
                "start": date(2026, 7, 2),
                "end": date(2026, 7, 5),
                "deliverable": "Descrição da arquitetura, pipeline, "
                               "assinatura estrutural, calibração "
                               "empírica dos pesos, decisões de projeto, "
                               "camada de confirmação manual + LLM.",
            },
            {
                "id": "M2.4",
                "name": "Capítulos de introdução e referencial teórico",
                "start": date(2026, 7, 6),
                "end": date(2026, 7, 8),
                "deliverable": "Introdução, objetivos, justificativa, "
                               "revisão de literatura (Defects4J "
                               "Dissection, APR clássica, abordagens "
                               "estruturais, uso de LLM em engenharia "
                               "de software).",
            },
        ],
    },
    {
        "id": "F3",
        "name": "Fase 3 — Revisão e ajustes",
        "start": date(2026, 7, 9),
        "end": date(2026, 7, 17),
        "objective": "Incorporar feedback do orientador e refinar o texto.",
        "milestones": [
            {
                "id": "M3.1",
                "name": "Revisão pelo orientador",
                "start": date(2026, 7, 9),
                "end": date(2026, 7, 15),
                "deliverable": "Texto enviado para revisão em 09/07; "
                               "janela de 7 dias para devolução do "
                               "orientador; reunião de feedback "
                               "registrada com lista de ajustes.",
            },
            {
                "id": "M3.2",
                "name": "Implementação dos ajustes",
                "start": date(2026, 7, 16),
                "end": date(2026, 7, 17),
                "deliverable": "Todas as observações do orientador "
                               "endereçadas; versão consolidada do TCC.",
            },
        ],
    },
    {
        "id": "F4",
        "name": "Fase 4 — Apresentação e entrega",
        "start": date(2026, 7, 18),
        "end": date(2026, 7, 20),
        "objective": "Preparar apresentação, ensaiar e entregar dentro do "
                     "prazo.",
        "milestones": [
            {
                "id": "M4.1",
                "name": "Slides, revisão final do texto e ensaio",
                "start": date(2026, 7, 18),
                "end": date(2026, 7, 19),
                "deliverable": "Slides finalizados (15-20 min); "
                               "demonstração ao vivo preparada; revisão "
                               "ortográfica e de formatação ABNT "
                               "concluída; ao menos 2 ensaios "
                               "cronometrados.",
            },
            {
                "id": "M4.2",
                "name": "ENTREGA FINAL",
                "start": date(2026, 7, 20),
                "end": date(2026, 7, 20),
                "deliverable": "PDF do TCC submetido à plataforma da "
                               "universidade; código publicado em "
                               "repositório citado.",
            },
        ],
    },
]

RISKS = [
    {
        "id": "R1",
        "description": "Implementação do 2º padrão atrasar por complexidade "
                       "inesperada na generalização",
        "probability": "Média",
        "impact": "Alto",
        "mitigation": "Escolher inicialmente um padrão sintaticamente "
                      "simples (ex.: `missNullCheckV` é variação direta do "
                      "atual); manter o atual como linha-base se necessário.",
    },
    {
        "id": "R2",
        "description": "Confirmação manual + LLM exigir mais tempo que os "
                       "10 dias alocados em M1.3 — análise de todos os "
                       "resultados pode ser ampla",
        "probability": "Média",
        "impact": "Médio",
        "mitigation": "Janela ampliada para 10 dias (10/06 a 19/06); se "
                      "exceder, priorizar a análise manual dos repos "
                      "principais (joda-time, error-prone) e tratar a "
                      "análise dos demais como anexo do TCC.",
    },
    {
        "id": "R3",
        "description": "Atraso no feedback do orientador",
        "probability": "Média",
        "impact": "Alto",
        "mitigation": "Agendar revisão com 4 semanas de antecedência; "
                      "janela de 7 dias reservada exclusivamente para "
                      "leitura do orientador (06/07 a 12/07). Em caso de "
                      "atraso adicional, encurtar M3.2 ou usar dias de "
                      "M4.1 como buffer.",
    },
    {
        "id": "R4",
        "description": "Rate limit do GitHub bloquear experimentos finais",
        "probability": "Baixa",
        "impact": "Baixo",
        "mitigation": "Cachear resultados em `results/*.json`; usar token "
                      "GitHub com 5000 reqs/h.",
    },
]

CRITICAL_PATH = [
    "M1.1 (testes) — encerrar até 26/05 (terça-feira); atraso reduz a "
    "janela de implementação do segundo padrão",
    "M1.2 (2º padrão) — bloqueia a confirmação manual + LLM",
    "M1.3 (confirmação manual + LLM) — gera o material que sustenta o "
    "capítulo de resultados, que abre a redação",
    "M2.1 (resultados e análises) — primeiro capítulo escrito, base para "
    "a conclusão",
    "M3.1 (revisão do orientador) — janela fixa de 7 dias",
    "M4.2 (entrega) — data inflexível: 20/07/2026",
]


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------
def make_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleBig",
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            alignment=1,
            spaceAfter=12,
            textColor=colors.HexColor("#1F2937"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="Subtitle",
            fontName="Helvetica",
            fontSize=13,
            leading=16,
            alignment=1,
            spaceAfter=18,
            textColor=colors.HexColor("#4B5563"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            spaceBefore=18,
            spaceAfter=10,
            textColor=colors.HexColor("#1F2937"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeading",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#374151"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            spaceAfter=6,
            textColor=colors.HexColor("#111827"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="Caption",
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=11,
            spaceAfter=8,
            textColor=colors.HexColor("#6B7280"),
        )
    )
    return styles


def fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def working_days(start: date, end: date) -> int:
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


def total_days(start: date, end: date) -> int:
    return (end - start).days + 1


def build_cover(styles) -> list:
    elems: list = []
    elems.append(Spacer(1, 5 * cm))
    elems.append(Paragraph(PROJECT_TITLE, styles["TitleBig"]))
    elems.append(Paragraph(SUBTITLE, styles["Subtitle"]))
    elems.append(Spacer(1, 2 * cm))
    cover_table = Table(
        [
            ["Autor", AUTHOR],
            ["Início do cronograma", fmt(START_DATE)],
            ["Entrega final", fmt(END_DATE)],
            ["Duração total", f"{total_days(START_DATE, END_DATE)} dias corridos"],
            ["Dias úteis", f"{working_days(START_DATE, END_DATE)} dias úteis"],
            ["Documento gerado em", fmt(GENERATED)],
        ],
        colWidths=[5 * cm, 8 * cm],
    )
    cover_table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 11),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 11),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1F2937")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ]
        )
    )
    elems.append(cover_table)
    elems.append(PageBreak())
    return elems


def build_summary(styles) -> list:
    elems: list = []
    elems.append(Paragraph("1. Resumo executivo", styles["SectionHeading"]))
    elems.append(
        Paragraph(
            "Este cronograma organiza as etapas finais do Trabalho de "
            "Conclusão de Curso (TCC) cujo tema é a detecção automática e "
            "interpretável de padrões de correção de bugs em repositórios "
            "Java do GitHub, baseada nos padrões catalogados pelo "
            "Defects4J Dissection. O sistema-base já está implementado e "
            "validado, com recall de 100% no ground truth do padrão "
            "<b>missNullCheckP</b>.",
            styles["Body"],
        )
    )
    elems.append(
        Paragraph(
            "Restam quatro fases: extensões técnicas (validação ampliada, "
            "segundo padrão, confirmação manual e LLM), redação, revisão "
            "pelo orientador e apresentação. A validação dos testes ocupa "
            "o primeiro mês até 26/05 (terça-feira). Em seguida o segundo "
            "padrão (até 09/06) e a confirmação manual + LLM aplicada a "
            "<b>todo o resultado</b> dos repositórios analisados (até "
            "19/06). A redação segue ordem inversa sugerida pelo "
            "orientador — começar pelo concreto: resultados e análises → "
            "conclusão → metodologia → introdução e referencial teórico "
            "(20/06 a 08/07). A revisão pelo orientador tem janela "
            "dedicada de 7 dias (09/07 a 15/07), seguida de 2 dias de "
            "ajustes. Apresentação e entrega ocorrem entre 18/07 e 20/07.",
            styles["Body"],
        )
    )
    elems.append(
        Paragraph(
            f"Período total: {fmt(START_DATE)} a {fmt(END_DATE)} "
            f"({total_days(START_DATE, END_DATE)} dias corridos / "
            f"{working_days(START_DATE, END_DATE)} dias úteis).",
            styles["Body"],
        )
    )
    return elems


def build_wbs(styles) -> list:
    elems: list = [Paragraph("2. Estrutura analítica (EAP / WBS)", styles["SectionHeading"])]
    elems.append(
        Paragraph(
            "A execução é dividida em quatro fases sequenciais. Cada fase "
            "contém marcos com data definida e entregável verificável.",
            styles["Body"],
        )
    )
    for phase in PHASES:
        elems.append(Paragraph(f"{phase['id']} · {phase['name']}", styles["SubHeading"]))
        elems.append(
            Paragraph(
                f"<b>Período:</b> {fmt(phase['start'])} a {fmt(phase['end'])} "
                f"({total_days(phase['start'], phase['end'])} dias) · "
                f"<b>Objetivo:</b> {phase['objective']}",
                styles["Body"],
            )
        )
        rows = [["ID", "Marco", "Início", "Fim", "Dias", "Entregável"]]
        for m in phase["milestones"]:
            rows.append(
                [
                    m["id"],
                    Paragraph(m["name"], styles["Body"]),
                    fmt(m["start"]),
                    fmt(m["end"]),
                    str(total_days(m["start"], m["end"])),
                    Paragraph(m["deliverable"], styles["Body"]),
                ]
            )
        table = Table(
            rows,
            colWidths=[1.2 * cm, 4.5 * cm, 2.1 * cm, 2.1 * cm, 1.0 * cm, 6.4 * cm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                    ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
                ]
            )
        )
        elems.append(KeepTogether([table]))
        elems.append(Spacer(1, 4 * mm))
    return elems


def build_gantt(styles) -> list:
    elems: list = [PageBreak(), Paragraph("3. Linha do tempo (Gantt simplificado)", styles["SectionHeading"])]
    elems.append(
        Paragraph(
            "Cada barra representa um marco. As semanas correspondem a "
            "intervalos de 7 dias a partir do início do cronograma.",
            styles["Caption"],
        )
    )
    weeks = []
    cur = START_DATE
    while cur <= END_DATE:
        weeks.append(cur)
        cur += timedelta(days=7)
    header = ["Marco"] + [f"S{i+1}\n{w.strftime('%d/%m')}" for i, w in enumerate(weeks)]
    rows = [header]
    for phase in PHASES:
        for m in phase["milestones"]:
            row = [Paragraph(f"<b>{m['id']}</b> {m['name']}", styles["Body"])]
            for w in weeks:
                w_end = w + timedelta(days=6)
                # Mark cell if the milestone overlaps with this week.
                if m["start"] <= w_end and m["end"] >= w:
                    row.append("█")
                else:
                    row.append("")
            rows.append(row)
    col_widths = [5.0 * cm] + [1.0 * cm] * len(weeks)
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    # Color the bar cells.
    for r, phase in enumerate(_flatten_milestones(), start=1):
        m = phase
        for ci, w in enumerate(weeks, start=1):
            w_end = w + timedelta(days=6)
            if m["start"] <= w_end and m["end"] >= w:
                style.append(("BACKGROUND", (ci, r), (ci, r), colors.HexColor("#10B981")))
                style.append(("TEXTCOLOR", (ci, r), (ci, r), colors.HexColor("#10B981")))
    table.setStyle(TableStyle(style))
    elems.append(table)
    return elems


def _flatten_milestones() -> list[dict]:
    out: list[dict] = []
    for phase in PHASES:
        out.extend(phase["milestones"])
    return out


def build_critical_path(styles) -> list:
    elems: list = [Paragraph("4. Caminho crítico", styles["SectionHeading"])]
    elems.append(
        Paragraph(
            "Sequência de marcos cujos atrasos comprometem diretamente a "
            "data de entrega final. Esses pontos devem ser monitorados "
            "semanalmente.",
            styles["Body"],
        )
    )
    for item in CRITICAL_PATH:
        elems.append(Paragraph(f"&bull; {item}", styles["Body"]))
    return elems


def build_risks(styles) -> list:
    elems: list = [Paragraph("5. Análise de riscos", styles["SectionHeading"])]
    elems.append(
        Paragraph(
            "Riscos identificados, com probabilidade, impacto e mitigação. "
            "A matriz segue a abordagem clássica de PMBOK / RACI.",
            styles["Body"],
        )
    )
    rows = [["ID", "Risco", "Prob.", "Impacto", "Mitigação"]]
    for r in RISKS:
        rows.append(
            [
                r["id"],
                Paragraph(r["description"], styles["Body"]),
                r["probability"],
                r["impact"],
                Paragraph(r["mitigation"], styles["Body"]),
            ]
        )
    table = Table(rows, colWidths=[1.2 * cm, 5.5 * cm, 1.5 * cm, 1.7 * cm, 7.4 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
            ]
        )
    )
    elems.append(table)
    return elems


def build_governance(styles) -> list:
    elems: list = [Paragraph("6. Governança e acompanhamento", styles["SectionHeading"])]
    elems.append(
        Paragraph(
            "<b>Reuniões de acompanhamento:</b> semanais com orientador, "
            "todas às sextas-feiras (15 min), até o início da Fase 3.",
            styles["Body"],
        )
    )
    elems.append(
        Paragraph(
            "<b>Indicador de progresso:</b> percentual de marcos concluídos "
            "em relação ao planejado. Meta: nunca abaixo de 80% no momento "
            "de cada reunião.",
            styles["Body"],
        )
    )
    elems.append(
        Paragraph(
            "<b>Critério de alerta:</b> qualquer marco do caminho crítico "
            "atrasado em mais de 3 dias dispara replanejamento imediato "
            "com redução de escopo (ex.: postergar LLM para trabalho "
            "futuro).",
            styles["Body"],
        )
    )
    elems.append(
        Paragraph(
            "<b>Ferramenta de tracking:</b> arquivo `progress.md` no "
            "repositório, atualizado ao final de cada semana, com status "
            "do marco em curso e blockers conhecidos.",
            styles["Body"],
        )
    )
    return elems


def build_footer_canvas(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#9CA3AF"))
    canvas.drawString(2 * cm, 1.2 * cm, PROJECT_TITLE)
    canvas.drawRightString(
        A4[0] - 2 * cm,
        1.2 * cm,
        f"página {doc.page}",
    )
    canvas.restoreState()


def main() -> int:
    output = Path("results/cronograma_tcc.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=PROJECT_TITLE,
        author=AUTHOR,
    )
    styles = make_styles()
    story: list = []
    story.extend(build_cover(styles))
    story.extend(build_summary(styles))
    story.extend(build_wbs(styles))
    story.extend(build_gantt(styles))
    story.extend(build_critical_path(styles))
    story.extend(build_risks(styles))
    story.extend(build_governance(styles))

    doc.build(story, onFirstPage=build_footer_canvas, onLaterPages=build_footer_canvas)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
