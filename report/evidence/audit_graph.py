import json
from pathlib import Path
from dotenv import load_dotenv
from bench_kg import connect_graph
load_dotenv('.env')
g = connect_graph()
queries = {
'counts': 'MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC',
'E1': 'MATCH (k:Case) WHERE NOT EXISTS { MATCH (k)-[:CHARGED_WITH]->() } RETURN k.name, k.doc_id, k.summary',
'E3_people': 'MATCH (p:Person)-[:INVOLVED_IN]->(k:Case) WITH p, collect({name:k.name, doc_id:k.doc_id}) AS cases WHERE size(cases)>1 RETURN p.name, cases',
'E3_substances': 'MATCH (s:Substance) RETURN s.name ORDER BY toLower(s.name)',
'E6': "MATCH (p:Person)-[r:INVOLVED_IN]->(k:Case) WHERE coalesce(r.charge, '') = '' RETURN p.name, r.role, r.sentence, k.name, k.doc_id",
'MDMA': "MATCH (k:Case)-[r:INVOLVES]->(s:Substance {name:'MDMA'}) OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(k) RETURN k.name, k.doc_id, k.summary, r.amount, collect(p.name) AS people",
}
try:
    data = {key:{'cypher':q,'rows':g.run(q)} for key,q in queries.items()}
    Path('report/evidence/graph_audit.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data,ensure_ascii=False,indent=2))
finally:
    g.close()
