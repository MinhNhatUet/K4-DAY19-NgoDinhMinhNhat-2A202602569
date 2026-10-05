"""Before/after evidence for the own ontology (run on the full graph after `bench_kg.py --judge`).

    PYTHONPATH=. python report/evidence/bonus_audit.py
"""
import json
from pathlib import Path

from dotenv import load_dotenv

from bench_kg import connect_graph
from src.graph import amount_to_grams, canonical_substance, find_substances, parse_threshold

# Offline self-check of the parsers the ontology depends on.
assert parse_threshold("MDMA có khối lượng từ 05 gam đến dưới 30 gam") == {"min_qty": 5.0, "max_qty": 30.0, "unit": "g"}
assert parse_threshold("cao côca có khối lượng từ 500 gam đến dưới 01 kilôgam")["max_qty"] == 1000.0
assert parse_threshold("MDMA có khối lượng 100 gam trở lên") == {"min_qty": 100.0, "max_qty": None, "unit": "g"}
assert amount_to_grams("hơn 9,6kg") == 9600.0 and amount_to_grams("5 viên") is None
assert canonical_substance("thuốc lắc") == "MDMA" and canonical_substance("ketamine") == "Ketamine"
assert canonical_substance("ma túy") is None
assert find_substances("Methamphetamine") == ["Methamphetamine"]

load_dotenv(".env")
g = connect_graph()
queries = {
    "labels": "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC",
    "rels": "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC",
    "substances": "MATCH (s:Substance) RETURN s.name AS name, s.aliases AS aliases ORDER BY toLower(s.name)",
    "q5_clause_by_threshold": """
        MATCH (p:Person {name:'Cái Quang Huy'})-[:INVOLVED_IN]->(k:Case)-[v:INVOLVES]->(s:Substance {name:'MDMA'})
        MATCH (k)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)
              -[:HAS_THRESHOLD]->(t:Threshold)-[:FOR_SUBSTANCE]->(s)
        WHERE v.grams >= t.min_qty AND (t.max_qty IS NULL OR v.grams < t.max_qty)
        RETURN v.amount AS amount, v.grams AS grams, a.id AS article, cl.number AS clause, t.point AS point,
               t.min_qty AS min_g, t.max_qty AS max_g, cl.penalty AS penalty""",
    "methamphetamine_to_law": """
        MATCH (k:Case)-[:INVOLVES]->(s:Substance {name:'Methamphetamine'})<-[:FOR_SUBSTANCE]-(t:Threshold)
        RETURN count(DISTINCT k) AS cases, count(DISTINCT t) AS thresholds""",
    "q6_mdma_cases": """
        MATCH (k:Case)-[r:INVOLVES]->(:Substance {name:'MDMA'})
        RETURN k.name AS case, k.doc_id AS doc_id, r.amount AS amount ORDER BY doc_id""",
}
try:
    data = {key: {"cypher": " ".join(q.split()), "rows": g.run(q)} for key, q in queries.items()}
finally:
    g.close()
Path("report/evidence/bonus_audit.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(data, ensure_ascii=False, indent=2))
