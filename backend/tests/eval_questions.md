Framework for types of questions to assess LLM response over:
Conceptual correctness/depth — precise explanation of a single concept
Conceptual distinction — differentiating two or more concepts and how they relate
Enumeration completeness — did the student hit all items on a fixed list
Open-ended example — no single right answer, evaluator judges plausibility and relevance
Applied reasoning — given a scenario, correctly apply a concept or mechanism to it

Chapter 1
Define evolvability → conceptual correctness/depth
Differentiate fault vs failure → conceptual distinction
What are the key metrics for scalability? → enumeration completeness
Give a practical example of human error causing a fault → open-ended example
Given a system that goes down when one node fails, identify which of the big 3 properties is violated and why → applied reasoning

Chapter 2
Define relational DB → conceptual correctness/depth
Differentiate relational vs document DB → conceptual distinction
What are the components of a MapReduce job? → enumeration completeness
Give an example of a situation where a graph data model would be useful → open-ended example
Given a many-to-many relationship scenario, identify whether document or relational model handles it better and why → applied reasoning
Chapter 3
Define indexing → conceptual correctness/depth
Differentiate clustered vs nonclustered index → conceptual distinction
What happens when a B-tree node exceeds its threshold size? → enumeration completeness
Give an example of data that requires star schema → open-ended example
Given a data storage scenario, choose row or column oriented and justify → applied reasoning
Chapter 4
What does 'async' actually mean? → conceptual correctness/depth
Define backward vs forward compatibility → conceptual distinction
Explain the steps of how old code can overwrite new data despite field preservation → enumeration completeness
Give an example of a useful RPC in an application → open-ended example
Given a counter example, show how a data race can occur and use distributed actor framework as an alternative → applied reasoning
Chapter 5
Explain synchronous vs asynchronous replication → conceptual distinction
Explain the steps of how a new follower is set up → enumeration completeness
Why is replication necessary? → conceptual correctness/depth
Give an example where replication lag results in an issue when reading your own writes → open-ended example
Given an example of a causality violation, explain what happened and why that was enabled → applied reasoning
Chapter 6
Why is partitioning useful? → conceptual correctness/depth
Explain the difference between a global and local secondary index → conceptual distinction
Explain what happens in dynamic partitioning when a node exceeds its threshold → enumeration completeness
Given the Twitter celebrity example, identify a partitioning issue that could arise → open-ended example
Give an example node layout partitioned on both primary key and GSI → applied reasoning
Chapter 7
What is ACID? → enumeration completeness
Explain what transactions are → conceptual correctness/depth
Write skew vs phantoms → conceptual distinction
Give an example of a lost update → open-ended example
Given an example of read skew, use snapshot isolation to show how the problem can be resolved → applied reasoning
Chapter 8
Time of day clock vs monotonic clock → conceptual distinction
Name the assumptions of the crash recovery fault model → enumeration completeness
Explain how a timeout too short to declare node failure causes issues → conceptual correctness/depth
Give an example of a fencing token being necessary to prevent a dangerous operation → open-ended example
Given a GC pause example causing a node to be marked dead, give a mitigation → applied reasoning
