// KG-3 multi-hop for the own ontology: legal basis of a case, choosing the clause by numeric threshold.
// Clause 1 is always returned (basic frame); other clauses only when the case amount falls in a Threshold.
MATCH (k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)
OPTIONAL MATCH (k)-[v:INVOLVES]->(s:Substance)<-[:FOR_SUBSTANCE]-(t:Threshold)<-[:HAS_THRESHOLD]-(cl)
WHERE v.grams >= t.min_qty AND (t.max_qty IS NULL OR v.grams < t.max_qty)
WITH k, a, cl, collect(s.name + ' ' + v.amount + ' -> điểm ' + t.point) AS matched
WHERE cl.number = 1 OR size(matched) > 0
RETURN k.name, a.id, cl.number, cl.penalty, matched
ORDER BY k.name, a.id, cl.number;
