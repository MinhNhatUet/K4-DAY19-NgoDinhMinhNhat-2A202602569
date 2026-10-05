"""Knowledge Graph (Neo4j) + GraphRAG over two drug-topic knowledge bases.

Contract (fixed — bench_kg.py and the tests rely on it):
    link_entity(name, known)                       -> one of `known` or None          (TODO KG-1)
    build_graph(graph, law_docs, news_docs, llm_fn)   load both KBs into Neo4j      (TODO KG-2)
        every node created from ONE document carries the property `doc_id`
    Neo4jGraph.context(question, doc_ids)         -> list[str] facts               (TODO KG-3)
    GraphRAGAgent.answer(question, top_k)         -> str                           (TODO KG-4)

Everything else in this file is a HINT: one possible ontology (below). Use it as is, change it,
or design your own — your own ontology + report/ONTOLOGY.md earns the bonus (see SUBMISSION.md).

Ontology used here (own design, see report/ONTOLOGY.md). Crime is the bridge between the two KBs;
quantity thresholds are first-class nodes so the applicable clause can be chosen by comparing numbers:

    (:Article {id, title, law, doc_id})-[:DEFINES]->(:Crime {name})
    (:Article)-[:HAS_CLAUSE]->(:Clause {id, number, penalty, text})
    (:Clause)-[:HAS_THRESHOLD]->(:Threshold {id, point, text, scope, unit, min_qty, max_qty})
    (:Threshold)-[:FOR_SUBSTANCE]->(:Substance {name, aliases})       # canonical name, synonyms in aliases
    (:Case {name, summary, date, doc_id})-[:CHARGED_WITH]->(:Crime)
    (:Case)-[:INVOLVES {amount, grams}]->(:Substance)
    (:Case)-[:LOCATED_IN]->(:Location {name})
    (:Person {name, aliases})-[:INVOLVED_IN {role, sentence, charge}]->(:Case)
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .models import Document
from .store import EmbeddingStore

# Canonical substance names: the ones BLHS Chương XX lists, plus common ones in Vietnamese news.
SUBSTANCES = ["Heroine", "Cocaine", "Methamphetamine", "Amphetamine", "MDMA", "XLR-11", "Ketamine",
              "cần sa", "thuốc phiện", "côca"]
# News wording -> canonical name; generic words are not a substance.
SUBSTANCE_SYNONYMS = {"thuốc lắc": "MDMA", "ma túy đá": "Methamphetamine", "ma tuý đá": "Methamphetamine",
                      "heroin": "Heroine", "cocain": "Cocaine", "coca": "côca"}
GENERIC_SUBSTANCES = {"ma túy", "ma tuý", "chất ma túy", "chất ma tuý", "ma túy tổng hợp", "ma tuý tổng hợp"}
CLAUSE_START = re.compile(r"^(\d+)\.\s", re.MULTILINE)
POINT_START = re.compile(r"^([a-zđ])\)\s", re.MULTILINE)
QTY = r"(\d+(?:,\d+)?) (gam|kilôgam|mililít|cây)"
RANGE = re.compile(rf"t[ừù] {QTY} đến dưới {QTY}")
AT_LEAST = re.compile(rf"{QTY} trở lên")
UNITS = {"gam": ("g", 1), "kilôgam": ("g", 1000), "mililít": ("ml", 1), "cây": ("cây", 1)}
AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kilôgam|kilogam|kg|gam|gram|g)(?!\w)", re.IGNORECASE)
FOOTNOTE = re.compile(r"\[\d+\]")

def load_markdown_docs(folder: str | Path) -> list[Document]:
    """Read crawler output (.md with a flat `key: "value"` front matter) into Documents."""
    docs = []
    for path in sorted(Path(folder).glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        _, front, body = raw.split("---", 2)
        metadata = {k: json.loads(v) for k, v in re.findall(r'^(\w+): (".*")$', front, re.MULTILINE)}
        docs.append(Document(id=metadata.get("doc_id", path.stem), content=body.strip(), metadata=metadata))
    return docs

def normalize_crime(name: str) -> str:
    """'Tội Mua bán trái phép chất ma túy' -> 'mua bán trái phép chất ma túy'."""
    name = re.sub(r"\s+", " ", name.strip().strip("\"'“”").lower())
    return name.removeprefix("tội ").strip()

def link_entity(name: str, known: list[str], normalize: Callable[[str], str] = normalize_crime) -> str | None:
    """Map a free-text mention (e.g. a charge written by a journalist) onto one canonical name in `known`."""
    normalized = normalize(name)
    if not normalized:
        return None
    canonical = {}
    for candidate in known:
        key = normalize(candidate)
        if key:
            canonical.setdefault(key, candidate)
    if normalized in canonical:
        return canonical[normalized]
    matches = difflib.get_close_matches(normalized, canonical, n=1, cutoff=0.8)
    return canonical[matches[0]] if matches else None

def find_substances(text: str) -> list[str]:
    # Word boundaries: "Amphetamine" must not match inside "Methamphetamine".
    return [name for name in SUBSTANCES if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE)]

def canonical_substance(name: str) -> str | None:
    """'thuốc lắc' -> 'MDMA', 'ketamine' -> 'Ketamine', 'ma túy' -> None, unknown -> lower-cased name."""
    key = re.sub(r"\s+", " ", name.strip().lower())
    if not key or key in GENERIC_SUBSTANCES:
        return None
    key = SUBSTANCE_SYNONYMS.get(key, key)
    return link_entity(key, SUBSTANCES, normalize=str.lower) or key

def _qty(number: str, unit: str) -> tuple[float, str]:
    unit_name, factor = UNITS[unit]
    return float(number.replace(",", ".")) * factor, unit_name

def parse_threshold(text: str) -> dict | None:
    """'... MDMA có khối lượng từ 05 gam đến dưới 30 gam' -> {min_qty: 5, max_qty: 30, unit: 'g'}."""
    if m := RANGE.search(text):
        (low, unit), (high, _) = _qty(*m.group(1, 2)), _qty(*m.group(3, 4))
        return {"min_qty": low, "max_qty": high, "unit": unit}
    if m := AT_LEAST.search(text):
        low, unit = _qty(*m.group(1, 2))
        return {"min_qty": low, "max_qty": None, "unit": unit}
    return None

def amount_to_grams(amount: str) -> float | None:
    """'hơn 9,6kg' -> 9600.0, '0,686g' -> 0.686, '5 viên' -> None.
    ponytail: ',' and '.' both read as decimal mark; '1.200g' (thousands) would parse as 1.2 g."""
    m = AMOUNT.search(amount or "")
    if not m:
        return None
    grams = float(m.group(1).replace(",", "."))
    return grams * 1000 if m.group(2).lower() in ("kg", "kilôgam", "kilogam") else grams

def parse_points(clause_id: str, text: str) -> list[dict]:
    """One Threshold per lettered point that states a quantity of named or 'other' substances."""
    starts = list(POINT_START.finditer(text))
    points = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        point_text = text[start.start():end].strip()
        threshold = parse_threshold(point_text)
        if not threshold or "chất ma túy trở lên" in point_text:   # "02 chất trở lên" mixtures: not modelled
            continue
        lowered = point_text.lower()
        scope = ("other_solid" if "chất ma túy khác ở thể rắn" in lowered
                 else "other_liquid" if "chất ma túy khác ở thể lỏng" in lowered else "listed")
        substances = find_substances(point_text) if scope == "listed" else []
        if scope == "listed" and not substances:
            continue
        points.append({"id": f"{clause_id} điểm {start.group(1)}", "point": start.group(1),
                       "text": point_text, "scope": scope, "substances": substances, **threshold})
    return points

# ----------------------------------------------------------------------------------------------
# HINT — suggested ontology: extraction helpers
# ----------------------------------------------------------------------------------------------

def parse_law_article(doc: Document) -> dict[str, Any]:
    """Deterministic (regex) extraction for one 'Điều' — law text is regular enough to skip the LLM."""
    article_id = doc.metadata["article"]                       # "Điều 251 BLHS"
    title = doc.metadata["title"].split(". ", 1)[-1]           # "Tội mua bán trái phép chất ma túy"
    body = FOOTNOTE.sub("", doc.content)
    starts = list(CLAUSE_START.finditer(body))
    clauses = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(body)
        text = body[start.start():end].strip()
        first_line = text.splitlines()[0]
        penalty = re.search(r"\bbị ((?:phạt|tù|cảnh cáo).+?)(?::|$)", first_line)
        clauses.append({
            "id": f"{article_id} khoản {start.group(1)}",
            "number": int(start.group(1)),
            "penalty": penalty.group(1).rstrip(".") if penalty else "",
            "text": text,
            "thresholds": parse_points(f"{article_id} khoản {start.group(1)}", text),
        })
    return {
        "id": article_id,
        "law": doc.metadata.get("law", ""),
        "title": title,
        "doc_id": doc.id,
        "crime": normalize_crime(title) if title.startswith("Tội ") else None,
        "clauses": clauses,
    }

NEWS_EXTRACTION_PROMPT = """Bạn trích xuất knowledge graph từ một bài báo tiếng Việt về ma túy.
Chỉ dùng thông tin có trong bài. Trả về JSON đúng dạng:
{{"cases": [{{
  "name": "tên ngắn của vụ việc, ví dụ: Vụ mua bán 36kg ma túy tại TP.HCM",
  "summary": "1-2 câu tóm tắt",
  "date": "ngày xảy ra/xét xử nếu có, dạng YYYY-MM-DD hoặc chuỗi rỗng",
  "location": "tỉnh/thành phố, chuỗi rỗng nếu không rõ",
  "charges": ["tội danh, BẮT BUỘC chọn đúng nguyên văn từ DANH SÁCH TỘI DANH"],
  "substances": [{{"name": "tên chất, dùng tên chuẩn trong DANH SÁCH CHẤT nếu khớp", "amount": "khối lượng nếu có"}}],
  "people": [{{"name": "họ tên", "aliases": ["biệt danh"], "role": "bị cáo|bị can|nghi phạm|người liên quan|cán bộ",
               "charge": "tội danh của người này (từ DANH SÁCH TỘI DANH) hoặc chuỗi rỗng",
               "sentence": "mức án nếu có, ví dụ: tử hình, 8 năm tù"}}]
}}]}}
Bài không nói về vụ việc cụ thể (tuyên truyền, hội nghị...) thì trả về {{"cases": []}}.
Chỉ trích vụ việc thuộc nội dung chính phù hợp với tiêu đề bài. Bỏ qua các đoạn giới thiệu
bài liên quan ở cuối bài; không tạo vụ, người hoặc khối lượng từ những đoạn giới thiệu đó.
Không gán tội danh hoặc khối lượng của một người cho tất cả người trong vụ.

DANH SÁCH TỘI DANH: {crimes}
DANH SÁCH CHẤT: {substances}

Tiêu đề: {title}
Nội dung:
{content}"""

def extract_news_cases(doc: Document, llm_fn: Callable[[str], str], known_crimes: list[str]) -> list[dict]:
    """LLM extraction for one news article; charges are re-linked to law-KB crimes in code."""
    prompt = NEWS_EXTRACTION_PROMPT.format(
        crimes="; ".join(known_crimes), substances=", ".join(SUBSTANCES),
        title=doc.metadata.get("title", ""), content=doc.content[:12000],
    )
    try:
        cases = json.loads(llm_fn(prompt)).get("cases", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    for case in cases:
        case["charges"] = sorted({c for c in (link_entity(x, known_crimes) for x in case.get("charges", [])) if c})
        for person in case.get("people", []):
            person["charge"] = link_entity(person.get("charge") or "", known_crimes) or ""
        substances = {}
        for item in case.get("substances", []):
            name = canonical_substance(item.get("name") or "")
            if name and name not in substances:
                amount = item.get("amount") or ""
                substances[name] = {"name": name, "alias": item["name"].strip(), "amount": amount,
                                    "grams": amount_to_grams(amount)}
        case["substances"] = list(substances.values())
    return cases

# ----------------------------------------------------------------------------------------------
# Neo4j
# ----------------------------------------------------------------------------------------------

class Neo4jGraph:
    """Thin wrapper over the official neo4j driver."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password), notifications_min_severity="OFF")
        self.driver.verify_connectivity()

    def close(self) -> None:
        self.driver.close()

    def run(self, cypher: str, **params: Any) -> list[dict]:
        records, _, _ = self.driver.execute_query(cypher, params)
        return [record.data() for record in records]

    def reset(self) -> None:
        """Delete every node, relationship and constraint (bench_kg.py calls this before build_graph)."""
        self.run("MATCH (n) DETACH DELETE n")
        for row in self.run("SHOW CONSTRAINTS YIELD name RETURN name"):
            self.run(f"DROP CONSTRAINT `{row['name']}` IF EXISTS")

    def stats(self) -> dict[str, int]:
        nodes = self.run("MATCH (n) RETURN count(n) AS n")[0]["n"]
        rels = self.run("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
        return {"nodes": nodes, "relationships": rels}

    def seed_facts(self, question: str, doc_ids: list[str], skip_labels: tuple[str, ...] = (),
                   limit: int = 60) -> tuple[list[str], list[str]]:
        """Ontology-independent first step: seed nodes + their 1-hop edges as text facts.

        Seeds = nodes whose `doc_id` is in doc_ids, or whose `name`/`aliases` appear in the question.
        Returns (seed elementIds, facts). Nodes with a label in skip_labels are left out of the facts.
        """
        seeds = self.run(
            """
            MATCH (n)
            WHERE n.doc_id IN $doc_ids
               OR (n.name IS :: STRING AND size(n.name) >= 3 AND toLower($q) CONTAINS toLower(n.name))
               OR any(a IN coalesce(n.aliases, []) WHERE size(a) >= 3 AND toLower($q) CONTAINS toLower(a))
            RETURN elementId(n) AS id
            """,
            q=question, doc_ids=doc_ids,
        )
        seed_ids = [row["id"] for row in seeds]
        edges = self.run(
            """
            MATCH (s)-[r]-(m)
            WHERE elementId(s) IN $ids
              AND none(l IN labels(s) + labels(m) WHERE l IN $skip)
            WITH DISTINCT r LIMIT $limit
            WITH startNode(r) AS a, r, endNode(r) AS b
            RETURN labels(a)[0] AS a_label, coalesce(a.name, a.id) AS a_name, type(r) AS rel,
                   properties(r) AS props, labels(b)[0] AS b_label, coalesce(b.name, b.id) AS b_name
            """,
            ids=seed_ids, skip=list(skip_labels), limit=limit,
        )
        facts = []
        for e in edges:
            props = ", ".join(f"{k}: {v}" for k, v in e["props"].items() if v)
            facts.append(f"({e['a_label']}: {e['a_name']}) -[{e['rel']}{' {' + props + '}' if props else ''}]-> "
                         f"({e['b_label']}: {e['b_name']})")
        return seed_ids, facts

    # ---------------------------------------------------------------- HINT — suggested ontology: writes

    def suggested_constraints(self) -> None:
        for label, key in [("Article", "id"), ("Clause", "id"), ("Threshold", "id"), ("Crime", "name"), ("Case", "name"),
                           ("Substance", "name"), ("Person", "name"), ("Location", "name")]:
            self.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")

    def add_law_article(self, article: dict) -> None:
        self.run(
            """
            MERGE (a:Article {id: $id}) SET a.title = $title, a.law = $law, a.doc_id = $doc_id
            FOREACH (crime IN CASE WHEN $crime IS NULL THEN [] ELSE [$crime] END |
                MERGE (c:Crime {name: crime}) ON CREATE SET c.doc_id = $doc_id
                MERGE (a)-[:DEFINES]->(c))
            WITH a
            UNWIND $clauses AS clause
            MERGE (cl:Clause {id: clause.id})
              SET cl.number = clause.number, cl.penalty = clause.penalty, cl.text = clause.text, cl.doc_id = $doc_id
            MERGE (a)-[:HAS_CLAUSE]->(cl)
            FOREACH (t IN clause.thresholds |
                MERGE (th:Threshold {id: t.id})
                  SET th.point = t.point, th.text = t.text, th.scope = t.scope, th.unit = t.unit,
                      th.min_qty = t.min_qty, th.max_qty = t.max_qty, th.doc_id = $doc_id
                MERGE (cl)-[:HAS_THRESHOLD]->(th)
                FOREACH (s IN t.substances | MERGE (sub:Substance {name: s})
                    ON CREATE SET sub.doc_id = $doc_id, sub.aliases = []
                    MERGE (th)-[:FOR_SUBSTANCE]->(sub)))
            """,
            **article,
        )

    def add_news_case(self, case: dict, doc: Document) -> None:
        self.run(
            """
            MERGE (k:Case {name: $name})
              SET k.summary = $summary, k.date = $date, k.doc_id = $doc_id, k.source_title = $title
            FOREACH (loc IN CASE WHEN $location = '' THEN [] ELSE [$location] END |
                MERGE (l:Location {name: loc}) ON CREATE SET l.doc_id = $doc_id
                MERGE (k)-[:LOCATED_IN]->(l))
            FOREACH (crime IN $charges | MERGE (c:Crime {name: crime})
                ON CREATE SET c.doc_id = $doc_id
                MERGE (k)-[:CHARGED_WITH]->(c))
            FOREACH (s IN $substances | MERGE (sub:Substance {name: s.name})
                ON CREATE SET sub.doc_id = $doc_id, sub.aliases = []
                SET sub.aliases = CASE WHEN toLower(s.alias) = toLower(sub.name) OR s.alias IN sub.aliases
                                       THEN sub.aliases ELSE sub.aliases + s.alias END
                MERGE (k)-[r:INVOLVES]->(sub)
                SET r.amount = s.amount, r.grams = s.grams)
            FOREACH (p IN $people | MERGE (person:Person {name: p.name})
                ON CREATE SET person.doc_id = $doc_id
                SET person.aliases = coalesce(p.aliases, [])
                MERGE (person)-[r:INVOLVED_IN]->(k) SET r.role = p.role, r.charge = p.charge, r.sentence = p.sentence)
            """,
            name=case.get("name") or doc.metadata.get("title", doc.id),
            summary=case.get("summary", ""), date=case.get("date", ""), location=case.get("location", ""),
            charges=case.get("charges", []), people=[p for p in case.get("people", []) if p.get("name")],
            substances=[s for s in case.get("substances", []) if s.get("name")],
            doc_id=doc.id, title=doc.metadata.get("title", ""),
        )

    # ---------------------------------------------------------------- KG-3

    def context(self, question: str, doc_ids: list[str], max_facts: int = 60) -> list[str]:
        """Graph facts for a question: seeds + 1 hop, then the legal basis of every case reached."""
        if max_facts <= 0:
            return []
        seed_ids, seed_facts = self.seed_facts(question, doc_ids, limit=max_facts)
        lowered = question.lower()
        all_clauses = any(word in lowered for word in ("tối đa", "cao nhất", "nặng nhất"))
        definition = any(word in lowered for word in ("là gì", "định nghĩa", "giải thích"))
        aggregation = any(word in lowered for word in ("những vụ", "các vụ", "bao nhiêu vụ"))
        substances = find_substances(question)
        article_numbers = re.findall(r"[Đđ]iều\s+(\d+)", question)

        # Aggregation starts from the substance across the whole graph, not just vector hits.
        cases = self.run(
            """
            MATCH (k:Case)
            WHERE CASE WHEN $aggregation AND size($substances) > 0
                THEN EXISTS { MATCH (k)-[:INVOLVES]->(s:Substance) WHERE s.name IN $substances }
                ELSE elementId(k) IN $ids OR EXISTS {
                    MATCH (s)-[]-(k) WHERE elementId(s) IN $ids
                } END
            RETURN elementId(k) AS id, k.name AS name, k.summary AS summary, k.doc_id AS doc_id
            ORDER BY k.doc_id, k.name
            """,
            ids=seed_ids, aggregation=aggregation, substances=substances,
        )
        case_ids = [row["id"] for row in cases]
        facts = [f"Vụ việc '{row['name']}' [{row['doc_id']}]: {row['summary']}" for row in cases]
        # Include every participant's own charge/sentence, rather than inheriting all case charges.
        people = self.run(
            """
            MATCH (p:Person)-[r:INVOLVED_IN]->(k:Case)
            WHERE elementId(k) IN $ids
            RETURN p.name AS person, k.name AS name, r.role AS role,
                   r.charge AS charge, r.sentence AS sentence
            ORDER BY k.name, p.name
            """, ids=case_ids,
        )
        facts.extend(
            f"{r['person']} trong vụ '{r['name']}': vai trò {r['role'] or 'chưa rõ'}; "
            f"tội danh {r['charge'] or 'chưa rõ'}; mức án {r['sentence'] or 'chưa có thông tin'}."
            for r in people
        )
        amounts = self.run(
            """
            MATCH (k:Case)-[r:INVOLVES]->(s:Substance)
            WHERE elementId(k) IN $ids
            RETURN k.name AS name, s.name AS substance, r.amount AS amount
            ORDER BY k.name, s.name
            """, ids=case_ids,
        )
        facts.extend(f"Vụ '{r['name']}' liên quan {r['substance']}: {r['amount'] or 'chưa rõ lượng'}."
                     for r in amounts)
        if aggregation:
            # One numbered line per case, no law text drowning it (E5): the answer is the set of cases.
            rows = self.run(
                """
                MATCH (k:Case) WHERE elementId(k) IN $ids
                OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(k)
                WITH k, collect(DISTINCT p.name) AS people
                OPTIONAL MATCH (k)-[v:INVOLVES]->(s:Substance) WHERE s.name IN $substances
                RETURN k.name AS name, k.doc_id AS doc_id, k.summary AS summary, people,
                       collect(s.name + ' ' + coalesce(nullif(v.amount, ''), 'chưa rõ lượng')) AS amounts
                ORDER BY k.doc_id
                """, ids=case_ids, substances=substances,
            )
            listing = [f"Truy vấn graph tìm được đúng {len(rows)} vụ việc; câu trả lời phải liệt kê đủ cả {len(rows)} vụ:"]
            listing += [f"{i}. Vụ '{r['name']}' [{r['doc_id']}]: {', '.join(r['amounts'])}; người liên quan: "
                        f"{', '.join(r['people']) or 'chưa rõ'}. {r['summary']}" for i, r in enumerate(rows, start=1)]
            return listing[:max_facts]
        # Numeric threshold match: case amount (grams) against Threshold nodes of the charged crime's Article.
        matched = self.run(
            """
            MATCH (k:Case)-[v:INVOLVES]->(s:Substance)
            WHERE elementId(k) IN $ids AND v.grams IS NOT NULL
            MATCH (k)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)
                  -[:HAS_THRESHOLD]->(t:Threshold {unit: 'g'})
            WHERE v.grams >= t.min_qty AND (t.max_qty IS NULL OR v.grams < t.max_qty)
              AND (EXISTS { (t)-[:FOR_SUBSTANCE]->(s) }
                   OR (t.scope = 'other_solid' AND NOT EXISTS {
                       MATCH (a)-[:HAS_CLAUSE]->()-[:HAS_THRESHOLD]->()-[:FOR_SUBSTANCE]->(s) }))
            RETURN k.name AS name, s.name AS substance, v.amount AS amount, v.grams AS grams,
                   a.id AS article, cl.id AS clause_id, cl.number AS number, t.point AS point, cl.penalty AS penalty
            ORDER BY name, article, number
            """, ids=case_ids,
        )
        facts.extend(
            f"Theo lượng {r['substance']} {r['amount']} (≈{r['grams']:g} gam) trong vụ '{r['name']}': áp dụng "
            f"{r['article']} khoản {r['number']} điểm {r['point']}, khung hình phạt: {r['penalty'] or 'xem văn bản khoản'}."
            for r in matched
        )
        clauses = self.run(
            """
            MATCH (k:Case)-[:CHARGED_WITH]->(c:Crime)<-[:DEFINES]-(a:Article)
                  -[:HAS_CLAUSE]->(cl:Clause)
            WHERE elementId(k) IN $ids AND ($all_clauses OR cl.number = 1 OR cl.id IN $matched OR EXISTS {
                MATCH (k)-[v:INVOLVES]->(:Substance)<-[:FOR_SUBSTANCE]-(:Threshold)<-[:HAS_THRESHOLD]-(cl)
                WHERE v.grams IS NULL
            })
            RETURN DISTINCT a.id AS article, a.title AS title, cl.number AS number, cl.text AS text
            ORDER BY article, number
            """, ids=case_ids, all_clauses=all_clauses, matched=[r["clause_id"] for r in matched],
        )
        # Law-only questions also need clause text: seed_facts only serializes edges.
        clauses += self.run(
            """
            MATCH (a:Article)-[:HAS_CLAUSE]->(cl:Clause)
            WHERE (elementId(a) IN $ids OR elementId(cl) IN $ids OR a.doc_id IN $doc_ids
                   OR any(n IN $numbers WHERE a.id STARTS WITH ('Điều ' + n + ' ')))
              AND ($all_clauses OR $definition OR cl.number = 1 OR EXISTS {
                  MATCH (cl)-[:HAS_THRESHOLD]->(:Threshold)-[:FOR_SUBSTANCE]->(s:Substance)
                  WHERE s.name IN $substances
              })
            RETURN DISTINCT a.id AS article, a.title AS title, cl.number AS number, cl.text AS text
            ORDER BY article, number
            """, ids=seed_ids, doc_ids=doc_ids, numbers=article_numbers,
            all_clauses=all_clauses, definition=definition, substances=substances,
        )
        law_facts = [f"[{r['article']} - {r['title']}] khoản {r['number']}: {r['text']}" for r in clauses]
        # Preserve legal context before generic one-hop edges consume the fact budget.
        ordered = law_facts + facts
        unique = list(dict.fromkeys(ordered + seed_facts))
        if len(unique) > max_facts:
            return unique[:max_facts - 1] + ["Ngữ cảnh graph đã bị giới hạn; danh sách dữ kiện có thể chưa đầy đủ."]
        return unique

# ---------------------------------------------------------------------------------------------- KG-2

def build_graph(graph: Neo4jGraph, law_docs: list[Document], news_docs: list[Document],
                llm_fn: Callable[..., str]) -> None:
    """Load both KBs into an empty graph. llm_fn(prompt, json_mode=False) -> str (metered OpenAI chat)."""
    graph.suggested_constraints()
    articles = [parse_law_article(doc) for doc in law_docs]
    for article in articles:
        graph.add_law_article(article)
    crimes = sorted({article["crime"] for article in articles if article["crime"]})
    for doc in news_docs:
        cases = extract_news_cases(doc, lambda prompt: llm_fn(prompt, json_mode=True), crimes)
        for case in cases:
            graph.add_news_case(case, doc)

# ---------------------------------------------------------------------------------------------- KG-4

GRAPH_PROMPT = """Trả lời câu hỏi chỉ dựa trên ngữ cảnh (đoạn văn bản và dữ kiện từ knowledge graph).
Nêu rõ số Điều luật và khoản khi có. Nếu dữ kiện graph có danh sách vụ việc, liệt kê đủ mọi vụ trong danh sách.
Nếu ngữ cảnh không đủ, nói không đủ thông tin.

Dữ kiện knowledge graph:
{facts}

Đoạn văn bản:
{chunks}

Câu hỏi: {question}
Trả lời:"""

class GraphRAGAgent:
    """Hybrid GraphRAG: the same vector top-k as flat RAG, plus facts expanded from the graph."""

    def __init__(self, store: EmbeddingStore, graph: Neo4jGraph, llm_fn: Callable[[str], str]) -> None:
        self.store = store
        self.graph = graph
        self.llm_fn = llm_fn

    def answer(self, question: str, top_k: int = 3) -> str:
        chunks = self.store.search(question, top_k=top_k)
        doc_ids = list(dict.fromkeys(
            chunk.get("metadata", {}).get("doc_id") for chunk in chunks
            if chunk.get("metadata", {}).get("doc_id")
        ))
        facts = self.graph.context(question, doc_ids)
        prompt = GRAPH_PROMPT.format(
            facts="\n".join(f"- {fact}" for fact in facts),
            chunks="\n\n".join(f"[{i}] {chunk['content']}" for i, chunk in enumerate(chunks, start=1)),
            question=question,
        )
        return self.llm_fn(prompt)
