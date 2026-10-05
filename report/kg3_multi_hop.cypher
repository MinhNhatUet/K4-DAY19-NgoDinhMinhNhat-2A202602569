// Tested via Neo4j driver before implementing context().
MATCH (k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)
WHERE cl.number = 1 OR EXISTS {
    MATCH (k)-[:INVOLVES]->(:Substance)<-[:MENTIONS]-(cl)
}
RETURN a.id, cl.number, cl.penalty
ORDER BY a.id, cl.number;
