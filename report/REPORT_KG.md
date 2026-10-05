# Báo cáo Day 19 — Flat RAG vs GraphRAG

**Họ tên:** Ngô Đình Minh Nhật  **MSSV:** 2A202602569  **Ngày:** 05/10/2026

> Kỳ vọng và thang điểm: `SUBMISSION.md`. Mọi số liệu phải khớp với `ket_qua_benchmark_kg.txt`. Bản thiết kế ontology nộp riêng ở `report/ONTOLOGY.md`.

Cấu hình (dòng đầu file kết quả): `openai:gpt-4o-mini`, `text-embedding-3-small`, top_k=3, chunk_size=800, 176 chunk, **KG: 207 nodes / 383 rels**.

## 1. Chi phí (10 điểm)

```
== Indexing (one-off)
pipeline  calls    in_tok  out_tok       USD  seconds
flat        176     56072        0   0.00112     43.6
graph       196     93318     4846   0.00962    102.9

== Querying (mean per question)
pipeline  recall  judge   in_tok  out_tok       USD  seconds
flat        0.43   1.17      694       47   0.00013     1.32
graph       0.94   1.83     6783       82   0.00106     2.15
```

| Chỉ số | Flat | Graph | Graph / Flat |
| --- | --- | --- | --- |
| Indexing USD | 0.00112 | 0.00962 | ×8.6 |
| Indexing giây | 43.6 | 102.9 | ×2.4 |
| Mỗi câu: USD | 0.00013 | 0.00106 | ×8.2 |
| Mỗi câu: giây | 1.32 | 2.15 | ×1.6 |
| Mỗi câu: in_tok | 694 | 6783 | ×9.8 |

**Chi phí tăng thêm đến từ đâu?**
> **Indexing:** graph gọi 196 lần, tức 176 lần embed chunk như Flat cộng 20 lần LLM trích vụ việc, mỗi bài báo một lần (luật parse bằng regex nên không tốn LLM). 20 lần này thêm 37 246 token đầu vào (93 318 − 56 072) và 4 846 token đầu ra, khoảng $0.0085, và chiếm phần lớn thời gian chênh (+59 giây).
> **Querying:** số lần gọi LLM vẫn như Flat (1 lần mỗi câu), nhưng prompt dài gấp ~9.8 lần vì `context()` đưa toàn bộ văn bản các khoản luật (mỗi khoản 1–2 nghìn ký tự) vào GRAPH_PROMPT, không chỉ cạnh. Câu Q6 chạm trần `max_facts=60`, phần lớn là text khoản luật (xem E5). Đầu ra cũng dài hơn (82 so với 47 token) vì có trích Điều/khoản.
>
> **Hòa vốn:** tính theo USD thì graph không bao giờ hòa vốn, vì mỗi câu đắt hơn $0.00093 và indexing đắt hơn $0.0085. Tính theo chi phí cho mỗi điểm judge: Flat $0.00013/1.17 ≈ $0.00011, Graph $0.00106/1.83 ≈ $0.00058. Với 1 000 câu, graph tốn thêm khoảng $0.93 + $0.0085 ≈ **$0.94**. Đổi lại, recall trung bình tăng từ 0.43 lên 0.94, và ở các câu cross-kb (Q3, Q4) Flat chỉ trả lời "Không đủ thông tin". Nếu một câu sai tốn hơn ~$0.002 công sửa của người, graph đã có lời.

## 2. Từng câu hỏi (10 điểm)

| Câu | Loại | Flat recall / judge | Graph recall / judge | Thắng | Vì sao (1 câu) |
| --- | --- | --- | --- | --- | --- |
| Q1 | single-hop-law | 1.00 / 2 | 1.00 / 2 | Hòa (Flat rẻ hơn) | Định nghĩa nằm gọn trong 1 chunk khoản 4 Điều 2 PCMT, vector search lấy trúng, graph chỉ thêm trích dẫn "khoản 4". |
| Q2 | single-hop-news | 1.00 / 2 | 1.00 / 2 | Hòa (Flat rẻ hơn) | Tên hai bị cáo tử hình nằm cùng chunk với "36kg" trong một bài; graph còn thêm "Điều 251" mà câu hỏi không cần. |
| Q3 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | Top-3 của Flat không chứa chunk Điều 251 nên trả lời "Không đủ thông tin"; graph đi `Person→Case→Crime←Article→Clause` lấy được khung "02 năm đến 07 năm". |
| Q4 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | Câu hỏi dùng biệt danh "Hoàng Nato" và không nhắc Điều luật; graph nối Case→"tổ chức sử dụng"→Điều 255 và lấy cả khoản 4 (chung thân). |
| Q5 | cross-kb-multi-hop | 0.60 / 2 | 1.00 / 2 | **Graph** | Flat đoán đúng khung phạt nhưng không nêu "Điều 250", "khoản 4" (chỉ nói "khoản b"); graph có Article.id và Clause.number nên trích chính xác. |
| Q6 | aggregation | 0.00 / 1 | 0.67 / 1 | **Graph** (cả hai chưa đủ) | Graph quét toàn bộ cạnh `INVOLVES→MDMA` nên tìm được vụ Cái Quang Huy và Lê Minh Thành; Flat chỉ thấy 3 chunk. Cả hai bỏ sót vụ Viện Pháp y tâm thần (E5). |

**Quy luật:** câu single-hop, khi đáp án nằm trong 1 chunk (Q1, Q2), thì hai bên hòa và Flat thắng về giá (rẻ hơn 8 lần). Câu cần nối hai KB (Q3–Q5) thì graph thắng tuyệt đối: recall cross-kb trung bình Flat 0.20, Graph 1.00. Câu tổng hợp (Q6) thì graph tốt hơn nhờ quét toàn graph thay vì top-k, nhưng vẫn bị giới hạn bởi bước sinh câu trả lời của LLM.

## 3. Phân tích lỗi (20 điểm)

### Lỗi E5: LLM lệch với graph ở câu aggregation (Q6)

- **Hiện tượng:** graph có **4** vụ liên quan MDMA, nhưng câu trả lời GraphRAG Q6 chỉ liệt kê **3** vụ và bỏ đúng vụ "Viện Pháp y tâm thần" có trong `must_include`, nên recall = 0.67.
- **Bằng chứng:** Cypher trả lời thẳng câu hỏi:

```cypher
MATCH (k:Case)-[r:INVOLVES]->(s:Substance {name:'MDMA'})
RETURN k.name, k.doc_id, r.amount;
```

```
Vụ tổ chức sử dụng ma túy tại Sầm Sơn       news-100260930085028036  0,686g
Vụ án tại Viện Pháp y tâm thần Trung ương    news-100260924105118645  ""
Vụ góp tiền mua ma túy tại Hà Nội            news-100260918080821054  5 viên
Vụ vận chuyển ma túy từ Đức về Việt Nam      news-100260917203001265  9.6kg
```

Câu trả lời GraphRAG Q6 (trích `ket_qua_benchmark_kg.txt`):
> 1. **Vụ vận chuyển ma túy từ Đức về Việt Nam** … 2. **Vụ góp tiền mua ma túy tại Hà Nội** … 3. **Vụ tổ chức sử dụng ma túy tại Sầm Sơn** … Tóm lại, ba vụ việc này đều có liên quan đến ma túy MDMA.

In thử `graph.context(Q6, [])` thì thấy dòng `Vụ 'Vụ án tại Viện Pháp y tâm thần Trung ương' liên quan MDMA: chưa rõ lượng.` **có trong** 60 dữ kiện. Vậy retrieval đúng, LLM bỏ sót.
Chạy lại benchmark lần 2: bản trước (recall 0.33) cũng liệt kê đúng 3 vụ đó và cũng bỏ Viện Pháp y. Riêng lượng MDMA của vụ Huy thì đổi từ "4,3kg" (lần 1) sang "hơn 9,6kg" (lần 2). Lỗi bỏ sót là **ổn định**, còn chi tiết số liệu thì **dao động**.

- **Nguyên nhân (bước generation + thiết kế context):** (1) 60 dữ kiện của Q6 gồm khoảng 15 dòng về vụ việc, còn lại là text dài của các khoản Điều 249–252 vì câu hỏi có chữ "MDMA" nên nhánh `MENTIONS` kéo luật vào. Dòng về Viện Pháp y bị chìm giữa hàng nghìn token text luật không liên quan. (2) Cạnh `INVOLVES` của vụ này có `amount` rỗng và summary nói về "nhận hối lộ… chạy giám định", nên LLM coi đây là vụ hối lộ chứ không phải vụ ma túy. (3) Vụ Sầm Sơn và Viện Pháp y là hai node riêng dù cùng nhóm người (Lê Văn Đông, Trần Quốc An, Nguyễn Thị Mai Anh), nên LLM có thể coi Sầm Sơn là "đại diện" và gộp mất một vụ.
- **Đề xuất sửa:** với câu aggregation, trả về đúng kết quả Cypher dạng danh sách (`RETURN DISTINCT k.name`), **không** kèm text khoản luật, và thêm vào prompt yêu cầu "liệt kê tất cả N vụ trong danh sách". Có thể bỏ hẳn LLM, render thẳng danh sách từ Cypher. Đặt `temperature=0` để lượng chất không dao động giữa các lần chạy.

### Lỗi E3: Trùng thực thể (Substance và Case)

- **Hiện tượng:** cùng một chất hoặc cùng một sự kiện bị tách thành nhiều node, làm gãy cầu phụ Substance và phân mảnh vụ việc.
- **Bằng chứng:**

```cypher
MATCH (s:Substance) WHERE toLower(s.name) IN ['ketamine','methamphetamine']
OPTIONAL MATCH (x)-[r]->(s)
RETURN s.name, type(r) AS rel, labels(x)[0] AS from, count(*) AS n ORDER BY s.name;
```

```
Ketamine         INVOLVES  Case    2
Methamphetamine  INVOLVES  Case    1
Methamphetamine  MENTIONS  Clause  18
ketamine         INVOLVES  Case    2
methamphetamine  INVOLVES  Case    2
```

Danh sách đầy đủ 16 Substance còn có các cặp đồng nghĩa hoặc chung chung: `MDMA` / `thuốc lắc`, `Cocaine` / `côca`, và các node rác `ma túy`, `chất ma túy`.

```cypher
MATCH (p:Person {name:'Dương Minh Tuấn'})-[:INVOLVED_IN]->(k:Case)
RETURN count(DISTINCT k) AS cases, collect(DISTINCT k.doc_id) AS docs;
```

```
cases: 4  docs: [news-100260925144412498, news-100260924095400982,
                 news-100260922111804786, news-100260920221957595]
```

Bốn bài cùng nói về việc bắt "Hoàng Nato", nhưng tạo ra 4 node `Case` khác tên ("Vụ bắt giang hồ 'Hoàng Nato' và 126 người liên quan", "Vụ bắt giữ TikToker Phannhibeauty và giang hồ 'Hoàng Nato'", …).

- **Nguyên nhân (bước extraction + khóa định danh trong ontology):** `MERGE` so khớp chuỗi chính xác và phân biệt hoa thường. Tên chất từ tin do LLM sinh ra, không được chuẩn hóa về danh mục của luật (`find_substances` chỉ áp dụng cho luật). Vì vậy 2 vụ dùng `methamphetamine` viết thường **không nối** được tới 18 khoản luật `MENTIONS Methamphetamine`. Với Case, khóa là `name` do LLM tự đặt theo từng bài, nên mỗi bài sinh một tên mới. Đây là giới hạn của ontology gợi ý mà `ONTOLOGY.md` mục 2 và 6.4 đã nêu.
- **Đề xuất sửa:** chạy tên chất qua `link_entity(name, SUBSTANCES, normalize=str.lower)` trước khi `MERGE` (dùng lại KG-1), thêm bảng đồng nghĩa (`thuốc lắc→MDMA`), và bỏ các tên chung như "ma túy". Với Case, hợp nhất theo (người chính + ngày + địa điểm) hoặc thêm bước gộp hậu kỳ: hai Case có chung ≥ 2 Person thì tạo cạnh `SAME_AS` hoặc gộp node.

### Lỗi E4: Phép đo sai, judge quá dễ ở Q5 (Flat)

- **Hiện tượng:** ở Q5, Flat có recall 0.60 nhưng judge = 2 (tối đa), bằng điểm GraphRAG (recall 1.00).
- **Bằng chứng:** `must_include` của Q5 là `['vận chuyển', 'MDMA', 'Điều 250', 'khoản 4', 'tử hình']`. Câu trả lời Flat Q5:
> … Với khối lượng MDMA hơn 9,6kg trong vụ này, **khoản b của điều luật tương ứng** được áp dụng, và khung hình phạt là từ 20 năm tù, tù chung thân hoặc tử hình.

Câu này không nêu Điều nào, và "khoản b" là sai: b là **điểm** b thuộc khoản 4, không phải khoản. Câu hỏi hỏi rõ "khoản nào của điều luật". Ngược lại, ở Q6 Flat có recall 0.00 nhưng judge = 1, dù câu trả lời liệt kê "vụ của Đức, Thành, Đông" mà không có tên đầy đủ hay vụ Cái Quang Huy.
- **Nguyên nhân (bước đánh giá):** LLM-judge chấm theo "ý chung" (khung hình phạt đúng thì cho điểm tối đa), không phạt khi thiếu trích dẫn pháp lý. Keyword recall thì quá cứng: nếu Flat viết "Điều 250" mà không có chữ "khoản 4" vẫn mất điểm. Ở câu này recall phản ánh đúng hơn judge.
- **Đề xuất sửa:** đưa `must_include` vào prompt của judge và yêu cầu trừ điểm khi thiếu từng mục. Hoặc dùng điểm tổng hợp `min(judge/2, recall)` cho các câu pháp lý cần trích dẫn chính xác.

## 4. Kết luận (5 điểm)

> **Nên dùng KG khi** câu hỏi cần **nối hai nguồn không cùng xuất hiện trong một chunk**, như tin tức (người, vụ) nối với luật (Điều, khoản). Ở 3 câu cross-kb, recall Flat chỉ đạt 0.00 / 0.00 / 0.60 (Q3, Q4 trả lời "Không đủ thông tin"), còn Graph đạt 1.00 / 1.00 / 1.00. KG cũng có lợi cho câu **tổng hợp** trên toàn corpus (Q6: 0.67 so với 0.00), vì graph quét toàn bộ cạnh thay vì chỉ top-3. Trung bình 6 câu: recall 0.43 → 0.94, judge 1.17 → 1.83.
>
> **Flat RAG là đủ khi** câu hỏi single-hop và đáp án nằm gọn trong một đoạn (Q1, Q2: hai bên đều 1.00 / 2). Khi đó graph chỉ tốn thêm ×8.2 USD, ×1.6 thời gian, ×9.8 token mỗi câu và ×8.6 USD indexing mà không tăng điểm.
>
> **Điều kiện cụ thể:** dữ liệu có thực thể lặp lại giữa các nguồn (tội danh, chất) và có cấu trúc (luật chia Điều/khoản, regex parse được); tỉ lệ câu multi-hop/aggregation đáng kể (ở đây 4/6); và chất lượng quan trọng hơn ~$0.94 cho 1 000 câu. Nếu phần lớn câu hỏi là tra cứu một đoạn, hoặc không có ngân sách để làm sạch thực thể (E3 cho thấy graph tự động vẫn trùng node), thì nên dùng Flat RAG, hoặc định tuyến: chỉ gọi graph khi câu hỏi nhắc người/vụ **và** hỏi về luật.

## 5. Tự kiểm (5 điểm)

```
$ pytest tests/ -q
................................................                         [100%]
48 passed in 0.06s

$ python bench_kg.py --check
[OK] Dữ liệu: 18 điều luật, 20 bài báo
[OK] KG-1 link_entity
[OK] Neo4j kết nối được
[provider] chat = openai:gpt-4o-mini | embedding = openai:text-embedding-3-small
[OK] KG-2 build_graph: 146 node / 289 cạnh, đường xuyên 2 KB dài 1 cạnh
[OK] KG-3 context: 19 dữ kiện, có Điều 251
[OK] KG-4 GraphRAGAgent.answer
[OK] Chi phí check: 1 lần gọi LLM, $0.00066. Graph nhỏ (luật + 1 bài) vẫn còn trong Neo4j để bạn xem; chạy --judge để dựng graph đầy đủ.
```

Sau đó chạy `python bench_kg.py --judge` trên code cuối để sinh lại `ket_qua_benchmark_kg.txt` (207 nodes / 383 rels). Các Cypher ở mục 3 chạy trên graph này. Kiểm tra các label và quan hệ đang có (khớp `ONTOLOGY.md`):

```
Labels: Clause 99, Person 40, Article 18, Substance 16, Case 14, Crime 13, Location 7
Rels:   MENTIONS 169, HAS_CLAUSE 99, INVOLVED_IN 48, INVOLVES 22, CHARGED_WITH 18, LOCATED_IN 14, DEFINES 13
```

Ảnh Neo4j: `report/img/kg_count.png`, `report/img/kg_cross_kb.png`, `report/img/kg_my_case.png`.
Người đã chọn cho `kg_my_case.png`: **Cái Quang Huy** (Person → Case "Vụ vận chuyển ma túy từ Đức về Việt Nam" → Crime "vận chuyển trái phép chất ma túy" ← Điều 250).

## Vấn đề gặp phải (không tính điểm)

> Ba ảnh được chụp từ lần dựng graph đầy đủ trước lần `--judge` cuối, nên `kg_count.png` ghi Person = 39, còn graph hiện tại có 40, vì mỗi lần chạy LLM trích xuất hơi khác nhau. Các label và quan hệ vẫn như cũ. Trên Windows, cần đặt `PYTHONIOENCODING=utf-8` để in tiếng Việt ra console.
