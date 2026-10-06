# Báo cáo Day 19 — Flat RAG vs GraphRAG

**Họ tên:** Ngô Đinh Minh Nhật  **MSSV:** 2A202602569  **Ngày:** 05/10/2026

> Kỳ vọng và thang điểm: `SUBMISSION.md`. Mọi số liệu phải khớp với `ket_qua_benchmark_kg.txt`. Bản thiết kế ontology nộp riêng ở `report/ONTOLOGY.md`.

Cấu hình (dòng đầu file kết quả): `openai:gpt-4o-mini`, `text-embedding-3-small`, top_k=3, chunk_size=800, 176 chunk, **KG: 319 nodes / 549 rels**. Graph dựng theo **ontology tự thiết kế** (`report/ONTOLOGY.md`, có `Threshold`). Kết quả của ontology gợi ý để so sánh: `ket_qua_benchmark_kg.hint.txt`.

## 1. Chi phí (10 điểm)

```
== Indexing (one-off)
pipeline  calls    in_tok  out_tok       USD  seconds
flat        176     56072        0   0.00112     40.9
graph       196     93318     4825   0.00960    100.6

== Querying (mean per question)
pipeline  recall  judge   in_tok  out_tok       USD  seconds
flat        0.43   1.00      694       47   0.00013     1.34
graph       1.00   2.00     5898      108   0.00094     2.39
```

| Chỉ số | Flat | Graph | Graph / Flat |
| --- | --- | --- | --- |
| Indexing USD | 0.00112 | 0.00960 | ×8.6 |
| Indexing giây | 40.9 | 100.6 | ×2.5 |
| Mỗi câu: USD | 0.00013 | 0.00094 | ×7.2 |
| Mỗi câu: giây | 1.34 | 2.39 | ×1.8 |
| Mỗi câu: in_tok | 694 | 5898 | ×8.5 |

**Chi phí tăng thêm đến từ đâu?**
> **Indexing:** 196 lần gọi = 176 lần embed chunk như Flat + **20 lần LLM trích xuất** (1 lần / bài báo). Luật, kể cả 117 node `Threshold`, được parse bằng regex nên không tốn LLM. 20 lần trích xuất thêm 37 246 token vào (93 318 − 56 072) và 4 825 token ra ≈ $0.0085, cùng ~60 giây.
> **Querying:** vẫn 1 lần gọi LLM / câu như Flat, nhưng prompt dài ×8.5 vì `context()` đưa **văn bản khoản luật** (1–2 nghìn ký tự / khoản) và danh sách vụ vào prompt. Output dài hơn (108 vs 47 token) vì có trích Điều/khoản và Q6 liệt kê 5 vụ.
> So với ontology gợi ý (`.hint.txt`), in_tok / câu giảm 6783 → 5898 (−13%) và USD / câu 0.00106 → 0.00094, vì nay chỉ đưa **khoản áp dụng theo lượng** chứ không đưa mọi khoản nhắc tới chất.
>
> **Hòa vốn:** theo USD thuần, graph không bao giờ hòa vốn (mỗi câu đắt thêm $0.00081, indexing đắt thêm $0.0085). Với 1 000 câu, graph tốn thêm ≈ **$0.82**. Theo chi phí / điểm judge: Flat $0.00013 / 1.00 = $0.00013, Graph $0.00094 / 2.00 = $0.00047. Đổi lại, recall tăng 0.43 → 1.00, và 3/6 câu Flat trả lời sai hoặc "Không đủ thông tin". Nếu mỗi câu sai tốn hơn ~$0.0015 công kiểm tra của người, graph có lời.

## 2. Từng câu hỏi (10 điểm)

| Câu | Loại | Flat recall / judge | Graph recall / judge | Thắng | Vì sao (1 câu) |
| --- | --- | --- | --- | --- | --- |
| Q1 | single-hop-law | 1.00 / 2 | 1.00 / 2 | Hòa (Flat rẻ hơn ×7) | Định nghĩa nằm gọn trong 1 chunk khoản 4 Điều 2 PCMT; graph chỉ thêm trích dẫn "Điều 2, khoản 4". |
| Q2 | single-hop-news | 1.00 / 2 | 1.00 / 2 | Hòa (Flat rẻ hơn) | Hai tên án tử hình cùng chunk với "36kg" trong một bài báo. |
| Q3 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | Top-3 của Flat không có chunk Điều 251 nên trả lời "Không đủ thông tin"; graph đi `Person→Case→Crime←Article→Clause 1` lấy được "02 năm đến 07 năm". |
| Q4 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | Câu hỏi chỉ có biệt danh; `Person.aliases` khớp "Hoàng Nato", Crime nối tới Điều 255 và nhánh "tối đa" lấy cả khoản 4 (chung thân). |
| Q5 | cross-kb-multi-hop | 0.60 / 1 | 1.00 / 2 | **Graph** | Flat nói "khoản b", không nêu Điều; graph so `9600 g ≥ 100 g` trên node `Threshold` và đưa thẳng "Điều 250 khoản 4 điểm b" vào context. |
| Q6 | aggregation | 0.00 / 1 | 1.00 / 2 | **Graph** | Flat chỉ thấy 3 chunk (gọi tên "Đức, Thành, Đông"); graph quét toàn bộ cạnh `INVOLVES→MDMA` và trả danh sách 5 vụ có tên người. |

**Quy luật:** câu single-hop có đáp án trong 1 chunk (Q1, Q2) thì hòa, và Flat thắng về giá. Câu cần nối hai KB (Q3–Q5) thì Graph thắng tuyệt đối: recall cross-kb Flat 0.20, Graph 1.00. Câu tổng hợp (Q6) thì Graph thắng nhờ quét toàn graph thay vì top-k, nhưng chỉ khi context là danh sách gọn: với ontology gợi ý, cùng câu này chỉ đạt 0.67 (lỗi E5 ở mục 3).

## 3. Phân tích lỗi (20 điểm)

### Lỗi E5: LLM lệch với graph ở câu aggregation (phát hiện trên ontology gợi ý, đã sửa)

- **Hiện tượng:** với ontology gợi ý, graph có đủ 4 vụ MDMA nhưng câu trả lời GraphRAG Q6 chỉ liệt kê 3 và bỏ vụ "Viện Pháp y tâm thần" (`must_include`), recall 0.67.
- **Bằng chứng** (trên graph của ontology gợi ý, `report/evidence/graph_audit.json`):

```cypher
MATCH (k:Case)-[r:INVOLVES]->(s:Substance {name:'MDMA'}) RETURN k.name, k.doc_id, r.amount;
```

```
Vụ tổ chức sử dụng ma túy tại Sầm Sơn       news-100260930085028036  0,686g
Vụ án tại Viện Pháp y tâm thần Trung ương    news-100260924105118645  ""
Vụ góp tiền mua ma túy tại Hà Nội            news-100260918080821054  5 viên
Vụ vận chuyển ma túy từ Đức về Việt Nam      news-100260917203001265  9.6kg
```

Câu trả lời Graph Q6 trong `ket_qua_benchmark_kg.hint.txt`:
> 1. Vụ vận chuyển ma túy từ Đức về Việt Nam … 2. Vụ góp tiền mua ma túy tại Hà Nội … 3. Vụ tổ chức sử dụng ma túy tại Sầm Sơn … Tóm lại, ba vụ việc trên đều có liên quan đến ma túy MDMA.

`graph.context(Q6, [])` **có** dòng `Vụ 'Vụ án tại Viện Pháp y tâm thần Trung ương' liên quan MDMA: chưa rõ lượng.`, nằm lẫn trong 60 dữ kiện mà phần lớn là text khoản Điều 249–252. Chạy benchmark 2 lần cho cùng kết quả: lần nào cũng bỏ sót vụ này, chỉ lượng MDMA của vụ Huy là dao động ("4,3kg" rồi "9,6kg").
- **Nguyên nhân (bước generation + thiết kế context):** chữ "MDMA" trong câu hỏi kéo nhánh `MENTIONS` vào, nên vài nghìn token luật không liên quan át mất dòng về vụ Viện Pháp y. Vụ này lại có `amount` rỗng và summary nói về "nhận hối lộ", nên LLM coi đó không phải vụ ma túy.
- **Đề xuất sửa (đã làm):** câu aggregation chỉ nhận danh sách vụ đánh số từ Cypher, có người liên quan, không kèm luật, và câu mở đầu "tìm được đúng N vụ; liệt kê đủ cả N vụ". Kết quả Q6: recall 0.67 → **1.00**, judge 1 → **2** (`ket_qua_benchmark_kg.txt`).

### Lỗi E3: Trùng thực thể (Substance đã sửa, Case vẫn còn)

- **Hiện tượng:** một thứ ngoài đời bị tách thành nhiều node.
- **Bằng chứng, Substance trên ontology gợi ý:**

```cypher
MATCH (s:Substance) WHERE toLower(s.name) IN ['ketamine','methamphetamine']
OPTIONAL MATCH (x)-[r]->(s) RETURN s.name, type(r), labels(x)[0], count(*);
```

```
Ketamine         INVOLVES  Case    2
Methamphetamine  INVOLVES  Case    1
Methamphetamine  MENTIONS  Clause  18
ketamine         INVOLVES  Case    2
methamphetamine  INVOLVES  Case    2      ← 2 vụ không nối được tới khoản luật nào
```

Ngoài ra có `MDMA` / `thuốc lắc` và các node rác `ma túy`, `chất ma túy` (16 Substance).

**Case trên graph hiện tại (vẫn còn):**

```cypher
MATCH (p:Person {name:'Dương Minh Tuấn'})-[:INVOLVED_IN]->(k:Case) RETURN count(DISTINCT k), collect(k.name);
```

```
4  ['Vụ triệt phá 8 đường dây ma túy tại TP.HCM', 'Vụ sử dụng ma túy etomidate của Hoàng Nato và Phan Kim Nhi',
    "Vụ bắt giữ TikToker Phannhibeauty và giang hồ 'Hoàng Nato'", "Vụ bắt giang hồ 'Hoàng Nato' và 126 người liên quan"]
```

- **Nguyên nhân (bước extraction + khóa trong ontology):** `MERGE` so chuỗi chính xác và phân biệt hoa thường. Tên chất do LLM viết không được đưa về danh mục chuẩn. `Case.name` do LLM tự đặt riêng cho từng bài.
- **Đề xuất sửa:** Substance **đã sửa** bằng `canonical_substance()` (đồng nghĩa + `link_entity` + bỏ tên chung). Sau khi sửa còn 11 Substance, và `Methamphetamine` của 3 vụ nối tới 18 `Threshold`. Với Case, cần khóa sự kiện (người chính + ngày + nơi) hoặc bước gộp hậu kỳ có kiểm tra. Gộp theo "chung ≥ 2 người" bị loại vì sẽ gộp nhầm vụ Viện Pháp y với vụ Sầm Sơn (cùng nhóm Lê Văn Đông, Trần Quốc An, Nguyễn Thị Mai Anh nhưng là hai vụ khác nhau).

### Lỗi E2/E6 (mới, do chính ontology tự thiết kế): lượng trích sai bị phép so sánh số khuếch đại

- **Hiện tượng:** ở vụ Hoàng Nato, graph "tự suy ra" khoản áp dụng cho Ketamine, nhưng con số 100 g không phải của Ketamine.
- **Bằng chứng:**

```cypher
MATCH (k:Case {doc_id:'news-100260920221957595'})-[r:INVOLVES]->(s) RETURN s.name, r.amount, r.grams;
```

```
MDMA       không rõ      null
etomidate  không rõ      null
Ketamine   khoảng 100g   100.0
```

Bài gốc viết: *"… hơn 1.000 đầu pod chill chứa ma túy etomidate, **khoảng 100g ma túy tổng hợp các loại** …"*. Từ đó `context()` sinh ra dữ kiện: `Theo lượng Ketamine khoảng 100g (≈100 gam) …: áp dụng Điều 251 BLHS khoản 3 điểm e, khung hình phạt: phạt tù từ 15 năm đến 20 năm.`
- **Nguyên nhân (bước extraction, bị thiết kế ontology khuếch đại):** LLM gán lượng "ma túy tổng hợp các loại" cho một chất cụ thể. Ở ontology gợi ý, lỗi này chỉ nằm im trong chuỗi `amount`. Ở ontology mới, `grams` được so với `Threshold`, nên lỗi biến thành một kết luận pháp lý trông rất chắc chắn. Lượng lại tính theo **vụ** chứ không theo người.
- **Đề xuất sửa:** yêu cầu LLM trả `evidence` (câu nguồn) cho mỗi lượng, và chỉ điền `grams` khi câu nguồn chứa đúng tên chất. Ghi kèm dữ kiện suy luận "(suy từ lượng do LLM trích, cần đối chiếu nguồn)". Chuyển `INVOLVES` sang `Person→Substance` khi bài nêu lượng riêng từng người.

### Lỗi E4: Phép đo sai — recall không phạt câu trả lời thừa

- **Hiện tượng:** Graph Q6 đạt recall 1.00 / judge 2, nhưng danh sách có 2 vụ ngoài kỳ vọng của benchmark.
- **Bằng chứng:** `must_include` của Q6 = `['Cái Quang Huy', 'Lê Minh Thành', 'Pháp y tâm thần']`. Câu trả lời Graph Q6 liệt kê thêm *"3. Vụ 'Vụ bắt giang hồ 'Hoàng Nato' …': MDMA không rõ"* và *"5. Vụ 'Vụ tổ chức sử dụng ma túy tại Sầm Sơn': MDMA 0,686g"*. Vụ Hoàng Nato vào danh sách vì bài viết "ketamine, **thuốc lắc**", và quy tắc `thuốc lắc→MDMA` (Substance.aliases = `['thuốc lắc']`) gộp nó vào MDMA. Ngược lại, Flat Q5 có recall 0.60 và judge 1, dù đúng khung hình phạt nhưng sai cách gọi "khoản b".
- **Nguyên nhân (bước đánh giá):** keyword recall chỉ đo độ phủ, không đo độ chính xác, nên liệt kê thừa không bị trừ điểm. LLM-judge chấm theo ý chung. Vụ Sầm Sơn thật ra có MDMA (0,686g) nên benchmark có thể đang thiếu đáp án.
- **Đề xuất sửa:** thêm `must_not_include` hoặc chấm precision cho câu aggregation. Đưa `must_include` vào prompt judge. Với ontology: thêm cờ `confirmed` trên `INVOLVES` (giám định xác nhận hay chỉ là từ lóng) để câu hỏi chặt có thể lọc.

## 4. Kết luận (5 điểm)

> **Nên dùng KG khi** câu hỏi cần **nối hai nguồn không cùng xuất hiện trong một chunk**, như tin tức (người, vụ, lượng) với luật (Điều, khoản, ngưỡng). Ở 3 câu cross-kb, recall Flat là 0.00 / 0.00 / 0.60, Graph là 1.00 / 1.00 / 1.00. Ở câu tổng hợp Q6, recall là 0.00 so với 1.00. Trung bình 6 câu: recall 0.43 → 1.00, judge 1.00 → 2.00. KG càng đáng tiền khi ontology mô hình hóa đúng cái câu hỏi cần **tính toán**: thêm `Threshold` làm Q5 trả lời được bằng phép so sánh số, và còn rẻ hơn ontology gợi ý (0.00106 → 0.00094 USD / câu).
>
> **Flat RAG là đủ khi** câu hỏi single-hop có đáp án nằm gọn trong một đoạn (Q1, Q2: cả hai đều 1.00 / 2). Khi đó graph chỉ tốn thêm ×7.2 USD, ×1.8 thời gian / câu và ×8.6 USD indexing mà không thêm điểm.
>
> **Điều kiện cụ thể:** (1) dữ liệu có thực thể lặp lại giữa các nguồn (tội danh, chất) và một nguồn có cấu trúc parse được bằng regex (luật); (2) tỉ lệ câu multi-hop / tổng hợp đáng kể (ở đây 4/6); (3) chấp nhận ~$0.82 / 1 000 câu và có người rà lỗi trích xuất, vì E2/E6 cho thấy graph có thể biến một lỗi LLM thành kết luận pháp lý sai trông rất chắc chắn. Nếu phần lớn câu hỏi là tra cứu một đoạn, dùng Flat, hoặc định tuyến: chỉ gọi graph khi câu hỏi vừa nhắc người/vụ vừa hỏi về luật hoặc hỏi "những vụ nào".

## 5. Tự kiểm (5 điểm)

```
$ pytest tests/ -q
................................................                         [100%]
48 passed in 0.07s

$ python bench_kg.py --check
[OK] Dữ liệu: 18 điều luật, 20 bài báo
[OK] KG-1 link_entity
[OK] Neo4j kết nối được
[provider] chat = openai:gpt-4o-mini | embedding = openai:text-embedding-3-small
[OK] KG-2 build_graph: 263 node / 459 cạnh, đường xuyên 2 KB dài 1 cạnh
[OK] KG-3 context: 19 dữ kiện, có Điều 251
[OK] KG-4 GraphRAGAgent.answer
[OK] Chi phí check: 1 lần gọi LLM, $0.00065. Graph nhỏ (luật + 1 bài) vẫn còn trong Neo4j để bạn xem; chạy --judge để dựng graph đầy đủ.
```

Sau đó chạy `python bench_kg.py --judge` trên code cuối để sinh `ket_qua_benchmark_kg.txt` (319 nodes / 549 rels). Các Cypher của graph hiện tại ở mục 3 và ảnh đều chạy trên graph này. Label / quan hệ thật: `Threshold 117, Clause 99, Person 40, Article 18, Case 14, Crime 13, Substance 11, Location 7`; `FOR_SUBSTANCE 222, HAS_THRESHOLD 117, HAS_CLAUSE 99, INVOLVED_IN 48, CHARGED_WITH 18, INVOLVES 18, LOCATED_IN 14, DEFINES 13`, khớp `ONTOLOGY.md`.

Ảnh Neo4j: `report/img/kg_count.png`, `report/img/kg_cross_kb.png`, `report/img/kg_my_case.png`.
Người đã chọn cho `kg_my_case.png`: **Cái Quang Huy**. Đường đi theo ontology của mình: Person → Case → Crime "vận chuyển trái phép chất ma túy" ← Điều 250 → khoản 4 → `Threshold` điểm b (MDMA ≥ 100 g) → MDMA ← Case (`grams` = 9600).

## Vấn đề gặp phải (không tính điểm)

> Trên Windows, cần đặt `PYTHONIOENCODING=utf-8` để in tiếng Việt ra console. LLM trích xuất mỗi lần chạy hơi khác nhau, nên số Person / Case dao động ±1 giữa các lần dựng graph. Mọi số trong báo cáo lấy từ lần `--judge` cuối.
