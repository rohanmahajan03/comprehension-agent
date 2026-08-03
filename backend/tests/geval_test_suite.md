# G-Eval Test Suite — Designing Data-Intensive Applications

## Question Categories
- **Conceptual correctness/depth** — precise explanation of a single concept
- **Conceptual distinction** — differentiating two or more concepts and how they relate
- **Enumeration completeness** — did the student hit all items on a fixed list
- **Open-ended example** — no single right answer, evaluator judges plausibility and relevance
- **Applied reasoning** — given a scenario, correctly apply a concept or mechanism to it

---

## Chapter 1

### Q1: Differentiate fault vs failure
**Category:** Conceptual distinction

**Golden answer:**
A fault is when an individual component of a system deviates from its specification. A failure is when the system as a whole stops providing the required service to the user. Faults are the cause; failures are the result. The goal of fault-tolerant systems is to prevent faults from escalating into failures.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) defined fault as a component-level deviation from specification, (2) defined failure as a system-level loss of service, and (3) articulated that faults cause failures. A judgment is poor if it awards credit to a response that conflates the two concepts, reverses the causal direction, or uses imprecise language like 'goes down' as a substitute for precise definitions.

**Student answer variants:**

1. *Clearly correct:*
A fault is when an individual component deviates from its specification — for example a disk returning corrupted data. A failure is when the system as a whole stops providing its required service to the user. Faults are the cause and failures are the result, so fault-tolerant systems aim to prevent faults from escalating into failures.

2. *Partially correct — defines both but misses causal relationship:*
A fault is when a component in a system stops working correctly. A failure is when the entire system goes down. They are both bad things that can happen in a distributed system.

3. *Clearly wrong — conflates the two:*
A fault and a failure are the same thing — they both refer to when a system stops working and is unavailable to users.

4. *Correct conclusion, wrong technical detail — causal direction reversed:*
A fault is when the entire system crashes. A failure is when an individual component misbehaves. Failures cause faults, so we try to prevent failures from escalating into faults.

---

### Q2: Given a system that goes down when one node fails, identify which of the big 3 properties is violated and why
**Category:** Applied reasoning

**Golden answer:**
The property violated is reliability. A reliable system should continue to work correctly even in the face of hardware faults such as a node going down. If the entire system fails when a single node fails, it has no fault tolerance — meaning a single hardware fault escalates directly into a system-wide failure.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) identified reliability as the violated property, (2) articulated that a reliable system should tolerate individual node failures and continue operating, and (3) connected the single node failure to a system-wide failure as the core problem. A judgment is poor if it awards credit to a response that identifies the wrong property, or accepts a vague justification like 'the system went down' without explaining why that constitutes a reliability violation.

**Student answer variants:**

1. *Clearly correct:*
The property violated is reliability. A reliable system should be able to tolerate individual node failures and continue serving requests. If the whole system goes down when one node fails, there is no fault tolerance and a single hardware fault escalates into a full system failure.

2. *Partially correct — identifies right property but weak justification:*
Reliability is violated because the system went down. A reliable system should not go down.

3. *Clearly wrong — identifies wrong property:*
The property violated is scalability. The system cannot handle the load when a node goes down, which means it is not scaling properly to meet demand.

4. *Correct conclusion, wrong justification:*
Reliability is violated because the system is not maintainable enough to recover from a node failure. The engineering team should have built better recovery mechanisms into the codebase.

---

## Chapter 2

### Q3: Given a many-to-many relationship scenario with students and courses, identify whether document or relational model handles it better and why
**Category:** Applied reasoning

**Golden answer:**
The relational model handles this better. Many-to-many relationships require joins — a student can be enrolled in many courses and a course can have many students. A relational database handles this naturally via a join table (e.g. an enrollments table with student_id and course_id). Document databases handle one-to-many relationships well via nesting, but struggle with many-to-many because they lack native join support, forcing you to either denormalize data or resolve references manually in application code.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) identified the relational model as the better fit, (2) explained that many-to-many relationships require joins, and (3) articulated why document databases struggle with this — either lack of native join support, denormalization, or manual reference resolution in application code. A judgment is poor if it awards credit to a response that identifies the correct model without justification, or accepts a vague answer like 'relational databases are better at relationships' without explaining why.

**Student answer variants:**

1. *Clearly correct:*
Relational is better here. A student can enroll in many courses and a course can have many students — this is a many-to-many relationship that requires joins. A relational database handles this naturally with a join table like enrollments with student_id and course_id. Document databases struggle with this because they don't support joins natively, so you'd have to denormalize or resolve references in application code.

2. *Partially correct — identifies right model but weak justification:*
Relational is better because document databases are not good at relationships. Relational databases are designed for this kind of thing.

3. *Clearly wrong — identifies wrong model:*
Document is better here. You can nest the courses a student is enrolled in directly inside the student document, making it easy to retrieve all of a student's courses in one query.

4. *Correct conclusion, wrong justification:*
Relational is better because relational databases are faster and more scalable than document databases for this type of query.

---

## Chapter 3

### Q4: Define indexing
**Category:** Conceptual correctness/depth

**Golden answer:**
An index is a separate data structure that allows a database to locate data efficiently without scanning the entire dataset. Indexes speed up read queries but slow down writes, since the index must be updated every time data is written. The choice of what to index is a tradeoff that is left to the application developer.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) described an index as a separate data structure that enables efficient data location without full dataset scans, and (2) articulated the read/write tradeoff. A judgment is poor if it awards credit to a response that only states indexes make queries faster without explaining the mechanism or tradeoff, or conflates an index with physically reorganizing or sorting the underlying data.

**Student answer variants:**

1. *Clearly correct:*
An index is a separate data structure that helps a database locate data efficiently without scanning the entire dataset. The tradeoff is that indexes speed up reads but slow down writes since the index needs to be updated on every write. The developer chooses what to index based on their query patterns.

2. *Partially correct — gets the purpose but misses the tradeoff:*
An index is a data structure that makes querying a database faster by organizing data so it can be found without scanning everything.

3. *Clearly wrong:*
An index is when you sort your database table alphabetically or numerically so that queries run faster.

4. *Correct but vague:*
An index helps a database find data faster. Without an index queries would be slow.

---

## Chapter 4

### Q5: What does async actually mean?
**Category:** Conceptual correctness/depth

**Golden answer:**
Async means that when a request is made, control returns to the caller as soon as the request is acknowledged rather than waiting for processing to complete. The work happens in the background and the caller has no guarantee about when it will finish.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) explained that control returns to the caller upon acknowledgement rather than completion, and (2) articulated that processing happens in the background with no guarantee of when it will finish. A judgment is poor if it awards credit to a response that conflates async with parallelism or multithreading, or accepts a vague answer like 'things happen without blocking' without explaining the acknowledgement vs completion distinction. A judgment should not penalize a response for correctly defining synchronous processing in addition to async.

**Student answer variants:**

1. *Clearly correct (includes sync definition):*
Async means that when a request is made, control returns to the caller immediately after the request is acknowledged, without waiting for the processing to complete. The work happens in the background and the caller has no guarantee about when it will finish. This is in contrast to synchronous processing where the caller blocks until the operation is complete.

2. *Partially correct — gets background processing but misses acknowledgement detail:*
Async means that work happens in the background so the caller doesn't have to wait. This makes systems faster.

3. *Clearly wrong — conflates async with parallelism:*
Async means that multiple requests are processed at the same time in parallel, allowing the system to handle more load.

4. *Correct but vague:*
Async means things happen without blocking. The caller doesn't have to wait for the response.

---

## Chapter 5

### Q6: Give an example where replication lag results in an issue when reading your own writes
**Category:** Open-ended example

**Golden answer:**
A user sees a question on a message board and replies with "fine." When they reload the page their reply appears to be gone. This is because the write went to the leader, but the subsequent read was served by a follower replica that had not yet caught up with the leader's replication lag. From the user's perspective they have lost their own write, even though it was successfully recorded on the leader.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) provided a plausible scenario where a user writes data and immediately reads it back, (2) correctly identified that the read was served by a replica that had not yet caught up with the leader due to replication lag, and (3) articulated that the write was successfully recorded but not yet visible to the reader. A judgment is poor if it penalizes a student for using a different but valid scenario, or awards credit to a response that cites the wrong mechanism such as transaction rollback, quorum failure, or disk persistence failure.

**Student answer variants:**

1. *Correct — message board scenario:*
A user posts a reply on a message board and immediately refreshes the page. Their reply is gone. This is because the write went to the leader but the read was served by a follower replica that hadn't yet caught up due to replication lag. The user appears to have lost their own write even though it was successfully recorded on the leader.

2. *Correct — banking scenario:*
A user transfers money from their checking account to their savings account and immediately checks their savings balance. The balance hasn't updated yet. This is because the write went to the leader but the subsequent read was served by a follower replica that hadn't yet caught up due to replication lag.

3. *Partially correct — right scenario, wrong mechanism:*
A user posts a reply on a message board and refreshes but the reply is gone. This is because of replication lag — the system hasn't synced yet so the user doesn't see their own write.

4. *Clearly wrong — wrong concept applied:*
A user posts a reply on a message board and refreshes but the reply is gone. This is because the database rolled back the transaction since it couldn't achieve a quorum of writes across all replicas.

5. *Clearly wrong — wrong concept entirely:*
A user posts a reply on a message board but it is gone because the server crashed and lost the write before it could be persisted to disk.

---

## Chapter 6

### Q7: Given a Twitter-like system partitioned by user_id, explain what issue arises when a celebrity with 10 million followers posts a tweet that receives a high volume of interactions
**Category:** Applied reasoning

**Golden answer:**
When a celebrity with a large following posts a tweet, all interactions with that tweet map to the same partition since the system is partitioned by user_id. That partition receives a disproportionately high volume of requests compared to all other partitions, becoming a hotspot. The load is not evenly distributed because one key generates far more traffic than others.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) identified that all interactions with the celebrity's tweet map to the same partition due to user_id based partitioning, and (2) articulated that this creates a hotspot where one partition receives disproportionately more traffic than others. A judgment is poor if it awards credit to a response that identifies a hotspot without explaining why partitioning by user_id causes it, or confuses the issue with replication, fan-out, or feed update problems.

**Student answer variants:**

1. *Clearly correct:*
Since the system is partitioned by user_id, all interactions with the celebrity's tweet map to the same partition. That partition gets overwhelmed with requests while all other partitions sit idle. The load is uneven because one key generates far more traffic than the others, creating a hotspot.

2. *Partially correct — identifies hotspot but misses why:*
The celebrity's partition becomes a hotspot because too many people are interacting with their tweet at once. This causes performance issues.

3. *Clearly wrong — confuses partitioning with replication:*
The issue is that the celebrity's tweet needs to be replicated to 10 million followers' feeds simultaneously, overwhelming the replication pipeline.

4. *Correct conclusion, wrong justification:*
The partition becomes a hotspot because the system is not using consistent hashing, which would distribute the celebrity's interactions evenly across all partitions.

---

### Q8: Give an example node layout partitioned on both primary key and GSI
**Category:** Open-ended example

**Golden answer:**
A system partitioned by user_id might have node A holding user_ids 1-1000 and node B holding user_ids 1001-2000. A GSI on favorite_color is partitioned independently — node C might hold all GSI entries for favorite_color = "blue", which stores the user_ids of all users whose favorite color is blue regardless of which primary key partition they belong to. To retrieve the full records, those user_ids are then looked up in their respective primary key partitions on node A or node B.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) described a valid primary key partitioning scheme with an example, (2) correctly described a GSI as partitioned independently of the primary key, (3) articulated that GSI entries point to primary keys rather than full records, and (4) explained that retrieving full records requires a second lookup in the primary key partition. A judgment is poor if it penalizes a student for using a different but valid example, or awards credit to a response that describes a local secondary index co-located with the primary key partition, or implies GSI entries store full records rather than pointers to primary keys.

**Student answer variants:**

1. *Clearly correct — range partitioned primary key:*
A system partitioned by user_id has node A holding user_ids 1-1000 and node B holding user_ids 1001-2000. A GSI on favorite_color is partitioned independently on node C, storing user_ids for all users whose favorite color is blue regardless of which primary key partition they belong to. To get the full record you look up those user_ids in their respective primary key partitions.

2. *Correct — hash partitioned primary key, different GSI attribute:*
A system uses hash partitioning on user_id, so user records are distributed across nodes A, B, and C based on a hash function rather than contiguous ranges. A GSI on favorite_food is partitioned independently on node D, storing user_ids for all users whose favorite food is pizza regardless of which node their primary key record lives on. To retrieve full records, those user_ids are hashed to find which node holds the primary key partition.

3. *Partially correct — describes local index instead of GSI:*
Node A holds user_ids 1-1000 and node B holds user_ids 1001-2000. Each node also stores a local index on favorite_color for the user_ids it contains, so node A has a favorite_color index for user_ids 1-1000 and node B has one for user_ids 1001-2000.

4. *Clearly wrong — confuses GSI with sorting:*
Node A holds user_ids 1-1000 sorted by favorite_color so that queries on favorite_color can be resolved without scanning the entire partition.

5. *Partially correct — gets GSI independence but misses pointer structure:*
Node C holds all records where favorite_color = "blue" copied directly from the primary key partitions, so a query on favorite_color can be resolved entirely from node C without touching node A or node B.

---

## Chapter 7

### Q9: What is ACID?
**Category:** Enumeration completeness

**Golden answer:**
ACID stands for Atomicity, Consistency, Isolation, and Durability. Atomicity means a transaction is never left in an intermediary state — either all writes in the transaction succeed or none do. Consistency means the database does not violate its invariants at any point. Isolation means concurrent transactions execute as if they were serial — they do not see each other's intermediate state. Durability means that once a transaction is committed, the data will not be lost even in the event of a fault.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has named and accurately defined all four ACID properties: (1) Atomicity — all writes succeed or none do, no intermediary state, (2) Consistency — the database never violates its invariants, (3) Isolation — concurrent transactions execute as if serial and do not see each other's intermediate state, (4) Durability — committed data is not lost even in the event of a fault. A judgment is poor if it awards full credit to a response that names all four properties but defines one or more incorrectly, or accepts vague definitions like 'data is saved permanently' as sufficient for durability without mentioning fault tolerance.

**Student answer variants:**

1. *Clearly correct:*
ACID stands for Atomicity, Consistency, Isolation, and Durability. Atomicity means all writes in a transaction succeed or none do. Consistency means the database never violates its invariants. Isolation means concurrent transactions don't see each other's intermediate state and execute as if they were serial. Durability means committed data is not lost even if the system crashes.

2. *Partially correct — misses one component:*
ACID stands for Atomicity, Consistency, Isolation, and Durability. Atomicity means all writes succeed or none do. Consistency means the database doesn't violate its invariants. Isolation means concurrent transactions don't interfere with each other. Durability is not something I remember clearly.

3. *Clearly wrong — gets letters right but wrong definitions:*
ACID stands for Atomicity, Consistency, Isolation, and Durability. Atomicity means the database processes one transaction at a time. Consistency means all replicas have the same data. Isolation means transactions are encrypted and secure. Durability means the database can recover from crashes.

4. *Partially correct — correct components but vague definitions:*
ACID means that databases handle transactions safely. Atomicity is all or nothing, consistency keeps the data correct, isolation keeps transactions separate, and durability means data is saved permanently.

---

## Chapter 8

### Q10: Time of day clock vs monotonic clock
**Category:** Conceptual distinction

**Golden answer:**
A time of day clock returns the current date and time and is synchronized across machines via NTP. However it can jump forwards or backwards due to NTP adjustments, making it unreliable for measuring elapsed time. A monotonic clock only moves forward and is suitable for measuring durations such as timeouts or response times on a single machine. NTP can slew a monotonic clock — speeding it up or slowing it down slightly — but cannot cause it to jump, preserving the monotonic guarantee. Monotonic clock values are meaningless in absolute terms and cannot be compared across machines.

**G-Eval criterion:**
A good evaluator judgment correctly identifies whether the student has: (1) described a time of day clock as returning current date and time, synchronized via NTP, but subject to forwards and backwards jumps making it unsuitable for measuring elapsed time, (2) described a monotonic clock as only moving forward, suitable for measuring durations on a single machine, and not comparable across machines, and (3) articulated that NTP can slew a monotonic clock but cannot cause it to jump. A judgment is poor if it awards credit to a response that describes the monotonic clock as synchronized across machines, or fails to penalize a response that incorrectly identifies the time of day clock as the safer option for measuring elapsed time.

**Student answer variants:**

1. *Clearly correct:*
A time of day clock returns the current date and time and is synchronized across machines via NTP, but can jump forwards or backwards due to NTP adjustments making it unreliable for measuring elapsed time. A monotonic clock only moves forward and is used for measuring durations like timeouts on a single machine. NTP can slew a monotonic clock by speeding it up or slowing it down but cannot cause it to jump. Monotonic clock values cannot be compared across machines.

2. *Partially correct — gets basic distinction but misses slewing and cross-machine limitation:*
A time of day clock tells you the current time and is synchronized with NTP but can jump backwards. A monotonic clock only moves forward so it is safer for measuring elapsed time like timeouts.

3. *Clearly wrong — confuses the two:*
A time of day clock is the safer option because it is synchronized across machines via NTP, making it reliable for measuring elapsed time in distributed systems. A monotonic clock can jump forwards and backwards which makes it unreliable.

4. *Partially correct — gets monotonic right but misses time of day clock dangers:*
A monotonic clock is suitable for measuring durations like timeouts because it always moves forward. A time of day clock tells you the current date and time and is synchronized across machines via NTP.
