# Graph Builder Golden Test Cases

Reference document for evaluating concept dependency graph extraction.
Each case is drawn from *Designing Data-Intensive Applications* (DDIA).
Each case includes the source text, expected concepts, expected edges, and tricky cases to watch for.

Structured into `tests/graph_geval/golden.py` for the automated suite — see `tests/graph_geval/` for the harness that runs `graph_builder._extract_raw_graph()` against the source text below and scores it against the expected concepts/edges here.

---

## Case 1 — Partitioning

**Source:** Chapter 6 — Partitioning of Key-Value Data, Secondary Indexes, Rebalancing

### Source Text

```
Partitioning and Replication
Partitioning is usually combined with replication so that copies of each partition are
stored on multiple nodes. This means that, even though each record belongs to
exactly one partition, it may still be stored on several different nodes for fault tolerance.
A node may store more than one partition. If a leader–follower replication model is
used, the combination of partitioning and replication can look like Figure 6-1. Each
partition's leader is assigned to one node, and its followers are assigned to other
nodes. Each node may be the leader for some partitions and a follower for other partitions.
Everything we discussed in Chapter 5 about replication of databases applies equally
to replication of partitions. The choice of partitioning scheme is mostly independent
of the choice of replication scheme, so we will keep things simple and ignore replication in this chapter.

Partitioning of Key-Value Data
Say you have a large amount of data, and you want to partition it. How do you decide
which records to store on which nodes?
Our goal with partitioning is to spread the data and the query load evenly across
nodes. If every node takes a fair share, then—in theory—10 nodes should be able to
handle 10 times as much data and 10 times the read and write throughput of a single
node (ignoring replication for now).
If the partitioning is unfair, so that some partitions have more data or queries than
others, we call it skewed. The presence of skew makes partitioning much less effective.
In an extreme case, all the load could end up on one partition, so 9 out of 10 nodes
are idle and your bottleneck is the single busy node. A partition with disproportionately high load is called a hot spot.
The simplest approach for avoiding hot spots would be to assign records to nodes
randomly. That would distribute the data quite evenly across the nodes, but it has a
big disadvantage: when you're trying to read a particular item, you have no way of
knowing which node it is on, so you have to query all nodes in parallel.
We can do better. Let's assume for now that you have a simple key-value data model,
in which you always access a record by its primary key.

Partitioning by Key Range
One way of partitioning is to assign a continuous range of keys (from some minimum
to some maximum) to each partition, like the volumes of a paper encyclopedia.
If you know the boundaries between the ranges, you can easily determine which partition
contains a given key. If you also know which partition is assigned to which node,
then you can make your request directly to the appropriate node.
The ranges of keys are not necessarily evenly spaced, because your data may not be
evenly distributed. In order to distribute the data evenly, the partition boundaries need to adapt to the data.
The partition boundaries might be chosen manually by an administrator, or the database
can choose them automatically. This partitioning strategy is used by Bigtable, HBase, RethinkDB, and MongoDB before version 2.4.
However, the downside of key range partitioning is that certain access patterns can
lead to hot spots. If the key is a timestamp, then the partitions correspond to ranges
of time—e.g., one partition per day. Unfortunately, because we write data from the
sensors to the database as the measurements happen, all the writes end up going to
the same partition (the one for today), so that partition can be overloaded with writes
while others sit idle.

Partitioning by Hash of Key
Because of this risk of skew and hot spots, many distributed datastores use a hash
function to determine the partition for a given key.
A good hash function takes skewed data and makes it uniformly distributed.
Once you have a suitable hash function for keys, you can assign each partition a
range of hashes (rather than a range of keys), and every key whose hash falls within a
partition's range will be stored in that partition.
This technique is good at distributing keys fairly among the partitions. The partition
boundaries can be evenly spaced, or they can be chosen pseudorandomly (in which
case the technique is sometimes known as consistent hashing).

Consistent Hashing
Consistent hashing, as defined by Karger et al., is a way of evenly distributing load
across an internet-wide system of caches such as a content delivery network (CDN).
Because this is so confusing, it's best to avoid the term consistent hashing and just call it hash partitioning instead.
Unfortunately however, by using the hash of the key for partitioning we lose a nice
property of key-range partitioning: the ability to do efficient range queries.

Skewed Workloads and Relieving Hot Spots
As discussed, hashing a key to determine its partition can help reduce hot spots.
However, it can't avoid them entirely: in the extreme case where all reads and writes
are for the same key, you still end up with all requests being routed to the same partition.

Partitioning and Secondary Indexes
The situation becomes more complicated if secondary indexes are involved.
A secondary index usually doesn't identify a record uniquely but rather is a way of
searching for occurrences of a particular value.
The problem with secondary indexes is that they don't map neatly to partitions.
There are two main approaches to partitioning a database with secondary indexes:
document-based partitioning and term-based partitioning.

Partitioning Secondary Indexes by Document
In this indexing approach, each partition is completely separate: each partition maintains
its own secondary indexes, covering only the documents in that partition.
For that reason, a document-partitioned index is also known as a local index (as opposed to a global index).
However, reading from a document-partitioned index requires care: you need to send the query to all partitions, and combine all the results you get back.
This approach to querying a partitioned database is sometimes known as scatter/gather.

Partitioning Secondary Indexes by Term
Rather than each partition having its own secondary index (a local index), we can
construct a global index that covers data in all partitions.
We call this kind of index term-partitioned, because the term we're looking for determines the partition of the index.
The advantage of a global (term-partitioned) index over a document-partitioned index is that it can make reads more efficient.
However, the downside of a global index is that writes are slower and more complicated.

Rebalancing Partitions
The process of moving load from one node in the cluster to another is called rebalancing.

Strategies for Rebalancing

Fixed number of partitions
Create many more partitions than there are nodes, and assign several partitions to each node.
This approach to rebalancing is used in Riak, Elasticsearch, Couchbase, and Voldemort.

Dynamic partitioning
For databases that use key range partitioning, a fixed number of partitions with fixed boundaries would be very inconvenient.
For that reason, key range-partitioned databases such as HBase and RethinkDB create partitions dynamically.
Dynamic partitioning is not only suitable for key range-partitioned data, but can equally well be used with hash-partitioned data.

Partitioning proportionally to nodes
A third option, used by Cassandra and Ketama, is to make the number of partitions proportional to the number of nodes.
Picking partition boundaries randomly requires that hash-based partitioning is used.
```

### Expected Concepts

| id | label | notes |
|---|---|---|
| `partitioning` | Partitioning | Core concept; aliases: sharding, shard, region, tablet, vnode, vBucket |
| `replication` | Replication | Cross-chapter reference (Ch5) — node only, no edges |
| `skew` | Skew | Prerequisite to understanding hot spots |
| `hot_spot` | Hot Spot | Defined clearly in text |
| `key_range_partitioning` | Key Range Partitioning | Fully explained |
| `hash_partitioning` | Hash Partitioning | Fully explained; absorbs "consistent hashing" as alias |
| `secondary_index` | Secondary Index | Defined and used as basis for two sub-concepts |
| `document_partitioned_index` | Document-Partitioned Index | aliases: local index |
| `term_partitioned_index` | Term-Partitioned Index | aliases: global index |
| `rebalancing` | Rebalancing | Fully defined section |
| `fixed_partition_rebalancing` | Fixed Number of Partitions | Rebalancing strategy |
| `dynamic_partitioning` | Dynamic Partitioning | Rebalancing strategy |
| `proportional_partitioning` | Partitioning Proportional to Nodes | Rebalancing strategy |

### Expected Edges

| from | to | evidence |
|---|---|---|
| `partitioning` | `skew` | "If the partitioning is unfair, so that some partitions have more data or queries than others, we call it skewed" |
| `skew` | `hot_spot` | "A partition with disproportionately high load is called a hot spot" |
| `hot_spot` | `key_range_partitioning` | "the downside of key range partitioning is that certain access patterns can lead to hot spots" |
| `hot_spot` | `hash_partitioning` | "Because of this risk of skew and hot spots, many distributed datastores use a hash function to determine the partition for a given key" |
| `key_range_partitioning` | `hash_partitioning` | "by using the hash of the key for partitioning we lose a nice property of key-range partitioning: the ability to do efficient range queries" |
| `secondary_index` | `document_partitioned_index` | "There are two main approaches to partitioning a database with secondary indexes: document-based partitioning and term-based partitioning" |
| `secondary_index` | `term_partitioned_index` | "There are two main approaches to partitioning a database with secondary indexes: document-based partitioning and term-based partitioning" |
| `document_partitioned_index` | `term_partitioned_index` | "Rather than each partition having its own secondary index (a local index), we can construct a global index" |
| `key_range_partitioning` | `dynamic_partitioning` | "For databases that use key range partitioning, a fixed number of partitions with fixed boundaries would be very inconvenient...key range-partitioned databases such as HBase and RethinkDB create partitions dynamically" |
| `hash_partitioning` | `proportional_partitioning` | "Picking partition boundaries randomly requires that hash-based partitioning is used" |
| `rebalancing` | `fixed_partition_rebalancing` | "Fixed number of partitions" is introduced as a strategy under the rebalancing section |
| `rebalancing` | `dynamic_partitioning` | Same as above |
| `rebalancing` | `proportional_partitioning` | Same as above |

### Tricky Cases

- **Consistent hashing** — text explicitly says to treat it as an alias for hash partitioning. Must not be a separate node.
- **hash mod N** — described as an anti-pattern, not a concept to learn. No node.
- **Scatter/gather** — named once as a label for a consequence of document-partitioned reads, not a standalone concept. Folded into `document_partitioned_index`.
- **`replication`** — node only. No edges sourced from Chapter 5 content. (The "combined with replication" sentence is proximity/reference language, not a prerequisite claim — this is the case Rule 3 exists for: a cross-chapter concept gets a node, not edges, unless *this* text explains the dependency.)

---

## Case 2 — Transactions and ACID

**Source:** Chapter 7 — The Meaning of ACID, Single/Multi-Object Operations, Weak Isolation Levels

### Source Text

```
A transaction is a way for an application to group several reads and writes
together into a logical unit. Conceptually, all the reads and writes in a transaction are
executed as one operation: either the entire transaction succeeds (commit) or it fails
(abort, rollback). If it fails, the application can safely retry. With transactions, error
handling becomes much simpler for an application, because it doesn't need to worry
about partial failure.

The Meaning of ACID
The safety guarantees provided by transactions are often described by the well-known
acronym ACID, which stands for Atomicity, Consistency, Isolation, and Durability.

Atomicity
ACID atomicity describes what happens if a client wants to make several writes, but a
fault occurs after some of the writes have been processed. If the writes are grouped
together into an atomic transaction, and the transaction cannot be completed (committed)
due to a fault, then the transaction is aborted and the database must discard or undo any
writes it has made so far in that transaction.
The ability to abort a transaction on error and have all writes from that transaction
discarded is the defining feature of ACID atomicity.

Consistency
The idea of ACID consistency is that you have certain statements about your data
(invariants) that must always be true. Atomicity, isolation, and durability are properties
of the database, whereas consistency (in the ACID sense) is a property of the application.

Isolation
Most databases are accessed by several clients at the same time. If they are accessing
the same database records, you can run into concurrency problems (race conditions).
Isolation in the sense of ACID means that concurrently executing transactions are
isolated from each other: they cannot step on each other's toes. The classic database
textbooks formalize isolation as serializability, which means that each transaction can
pretend that it is the only transaction running on the entire database.
However, in practice, serializable isolation is rarely used, because it carries a performance penalty.

Durability
Durability is the promise that once a transaction has committed successfully, any data
it has written will not be forgotten, even if there is a hardware fault or the database crashes.

Single-Object and Multi-Object Operations
Atomicity and isolation describe what the database should do if a client makes several
writes within the same transaction. Such multi-object transactions are often needed if
several pieces of data need to be kept in sync.
A transaction is usually understood as a mechanism for grouping multiple operations
on multiple objects into one unit of execution.

Weak Isolation Levels
Concurrency issues (race conditions) only come into play when one transaction reads
data that is concurrently modified by another transaction, or when two transactions
try to simultaneously modify the same data.
Serializable isolation has a performance cost, and many databases don't want to pay
that price. It's therefore common for systems to use weaker levels of isolation, which
protect against some concurrency issues, but not all.

Read Committed
The most basic level of transaction isolation is read committed. It makes two guarantees:
1. When reading from the database, you will only see data that has been committed (no dirty reads).
2. When writing to the database, you will only overwrite data that has been committed (no dirty writes).

No dirty reads
Transactions running at the read committed isolation level must prevent dirty reads.
This means that any writes by a transaction only become visible to others when that transaction commits.

No dirty writes
Transactions running at the read committed isolation level must prevent dirty writes,
usually by delaying the second write until the first write's transaction has committed or aborted.

Snapshot Isolation and Repeatable Read
However, there are still plenty of ways in which you can have concurrency bugs when
using this isolation level. This anomaly is called a nonrepeatable read or read skew.

Snapshot isolation is the most common solution to this problem. The idea is that each
transaction reads from a consistent snapshot of the database—that is, the transaction
sees all the data that was committed in the database at the start of the transaction.

Implementing snapshot isolation
The database must potentially keep several different committed versions of an object,
because various in-progress transactions may need to see the state of the database at
different points in time. Because it maintains several versions of an object side by side,
this technique is known as multi-version concurrency control (MVCC).
```

### Expected Concepts

| id | label | notes |
|---|---|---|
| `transaction` | Transaction | Core concept; commit/abort/rollback are properties, not separate nodes |
| `acid` | ACID | The four properties together as a named guarantee |
| `atomicity` | Atomicity | Fully explained; abortability is an alias |
| `consistency_acid` | Consistency (ACID) | Disambiguated from replica consistency — text explicitly flags the overloading |
| `isolation` | Isolation | Fully explained; serializability introduced as formal definition |
| `durability` | Durability | Fully explained |
| `multi_object_transaction` | Multi-Object Transaction | Distinct from single-object; text draws the line explicitly |
| `single_object_operation` | Single-Object Operation | Contrasted with multi-object |
| `race_condition` | Race Condition | Prerequisite to understanding why isolation matters |
| `read_committed` | Read Committed | Fully explained with two guarantees |
| `dirty_read` | Dirty Read | Anomaly prevented by read committed |
| `dirty_write` | Dirty Write | Anomaly prevented by read committed |
| `read_skew` | Read Skew | Anomaly not prevented by read committed; aliases: nonrepeatable read |
| `snapshot_isolation` | Snapshot Isolation | Fully explained as solution to read skew |
| `mvcc` | Multi-Version Concurrency Control (MVCC) | Implementation mechanism for snapshot isolation |

### Expected Edges

| from | to | evidence |
|---|---|---|
| `transaction` | `acid` | "The safety guarantees provided by transactions are often described by the well-known acronym ACID" |
| `acid` | `atomicity` | "ACID, which stands for Atomicity, Consistency, Isolation, and Durability" |
| `acid` | `consistency_acid` | "ACID, which stands for Atomicity, Consistency, Isolation, and Durability" |
| `acid` | `isolation` | "ACID, which stands for Atomicity, Consistency, Isolation, and Durability" |
| `acid` | `durability` | "ACID, which stands for Atomicity, Consistency, Isolation, and Durability" |
| `transaction` | `multi_object_transaction` | "A transaction is usually understood as a mechanism for grouping multiple operations on multiple objects into one unit of execution" |
| `atomicity` | `multi_object_transaction` | "atomicity and isolation describe what the database should do if a client makes several writes within the same transaction" |
| `isolation` | `multi_object_transaction` | "atomicity and isolation describe what the database should do if a client makes several writes within the same transaction" |
| `race_condition` | `isolation` | "if they are accessing the same database records, you can run into concurrency problems (race conditions)...Isolation in the sense of ACID means that concurrently executing transactions are isolated from each other" |
| `isolation` | `read_committed` | "The most basic level of transaction isolation is read committed" |
| `isolation` | `snapshot_isolation` | "Snapshot isolation is the most common solution to this problem" |
| `read_committed` | `dirty_read` | "When reading from the database, you will only see data that has been committed (no dirty reads)" |
| `read_committed` | `dirty_write` | "When writing to the database, you will only overwrite data that has been committed (no dirty writes)" |
| `read_committed` | `read_skew` | "there are still plenty of ways in which you can have concurrency bugs when using this isolation level...This anomaly is called a nonrepeatable read or read skew" |
| `read_skew` | `snapshot_isolation` | "Snapshot isolation is the most common solution to this problem" |
| `snapshot_isolation` | `mvcc` | "the database must potentially keep several different committed versions of an object...this technique is known as multi-version concurrency control (MVCC)" |

### Tricky Cases

- **Serializability** — introduced as the formal definition of isolation and contrasted with snapshot isolation, but deep treatment is deferred. Include as a concept node if it appears in the text being tested; edges into it from this section are weak.
- **`consistency_acid`** — must carry the ACID qualifier in its label to distinguish from replica consistency (Ch5) and linearizability (Ch9).
- **BASE** — mentioned once as "not ACID." Not a concept being taught. No node.
- **Row-level locking** — implementation detail of read committed. No node.
- **`weak_isolation`** — dropped; boundary between isolation and weak isolation is blurry in the text. Wire isolation levels directly to `isolation`.

---

## Case 3 — Storage Engines

**Source:** Chapter 3 — Hash Indexes, SSTables, LSM-Trees, B-Trees

### Source Text

```
Data Structures That Power Your Database

Consider the world's simplest database, implemented as two Bash functions.
Our db_set function has pretty good performance because appending to a file is generally
very efficient. Many databases internally use a log, which is an append-only data file.
On the other hand, our db_get function has terrible performance if you have a large
number of records in your database. In order to efficiently find the value for a particular
key in the database, we need a different data structure: an index.
An index is an additional structure that is derived from the primary data. Any kind of
index usually slows down writes, because the index also needs to be updated every time
data is written.

Hash Indexes
The simplest possible indexing strategy is this: keep an in-memory hash map where
every key is mapped to a byte offset in the data file. Whenever you append a new key-value
pair to the file, you also update the hash map to reflect the offset of the data you just wrote.
A good solution is to break the log into segments of a certain size by closing a segment
file when it reaches a certain size, and making subsequent writes to a new segment file.
We can then perform compaction on these segments. Compaction means throwing away
duplicate keys in the log, and keeping only the most recent update for each key.
Since compaction often makes segments much smaller, we can also merge several segments
together at the same time as performing the compaction.
The hash table index also has limitations:
- The hash table must fit in memory.
- Range queries are not efficient.

SSTables and LSM-Trees
Now we can make a simple change to the format of our segment files: we require that
the sequence of key-value pairs is sorted by key. We call this format Sorted String Table,
or SSTable for short. We also require that each key only appears once within each merged
segment file (the compaction process already ensures that).

Constructing and maintaining SSTables
When a write comes in, add it to an in-memory balanced tree data structure. This in-memory
tree is sometimes called a memtable. When the memtable gets bigger than some threshold,
write it out to disk as an SSTable file.

Making an LSM-tree out of SSTables
The algorithm described here is essentially what is used in LevelDB and RocksDB.
Originally this indexing structure was described by Patrick O'Neil et al. under the name
Log-Structured Merge-Tree (or LSM-Tree).

Performance optimizations
The LSM-tree algorithm can be slow when looking up keys that do not exist in the database.
In order to optimize this kind of access, storage engines often use additional Bloom filters.
A Bloom filter is a memory-efficient data structure for approximating the contents of a set.
It can tell you if a key does not appear in the database, and thus saves many unnecessary disk reads.

B-Trees
The most widely used indexing structure is quite different: the B-tree.
Like SSTables, B-trees keep key-value pairs sorted by key, which allows efficient key-value
lookups and range queries. By contrast, B-trees break the database down into fixed-size
blocks or pages, and read or write one page at a time.

Making B-trees reliable
In order to make the database resilient to crashes, it is common for B-tree implementations
to include an additional data structure on disk: a write-ahead log (WAL, also known as a redo log).
This is an append-only file to which every B-tree modification must be written before it can be
applied to the pages of the tree itself.

Comparing B-Trees and LSM-Trees
A B-tree index must write every piece of data at least twice: once to the write-ahead log,
and once to the tree page itself. Log-structured indexes also rewrite data multiple times due
to repeated compaction and merging of SSTables. This effect—one write to the database
resulting in multiple writes to the disk over the course of the database's lifetime—is known
as write amplification.
LSM-trees are typically faster for writes, whereas B-trees are thought to be faster for reads.
```

### Expected Concepts

| id | label | notes |
|---|---|---|
| `append_only_log` | Append-Only Log | Foundation concept |
| `log_segment` | Segmentation | Prerequisite to compaction and SSTable discussion |
| `hash_index` | Hash Index | First indexing structure; built on append-only log |
| `compaction` | Compaction | Defined clearly; applies to both hash index segments and SSTables |
| `sstable` | SSTable (Sorted String Table) | Key improvement over unsorted log segments; sparse in-memory index is an implementation detail, not a separate node |
| `memtable` | Memtable | In-memory buffer that feeds into SSTable writes |
| `lsm_tree` | LSM-Tree (Log-Structured Merge-Tree) | Full pipeline: memtable + SSTables + compaction |
| `bloom_filter` | Bloom Filter | Performance optimization for LSM-trees |
| `b_tree` | B-Tree | Fully explained as alternative to log-structured indexes |
| `write_ahead_log` | Write-Ahead Log (WAL) | Crash recovery mechanism for B-trees |
| `write_amplification` | Write Amplification | Defined in context of comparing B-trees and LSM-trees |

### Expected Edges

| from | to | evidence |
|---|---|---|
| `append_only_log` | `hash_index` | "the simplest possible indexing strategy is this: keep an in-memory hash map where every key is mapped to a byte offset in the data file" |
| `append_only_log` | `log_segment` | "break the log into segments of a certain size by closing a segment file when it reaches a certain size" |
| `log_segment` | `compaction` | "We can then perform compaction on these segments...throwing away duplicate keys in the log, and keeping only the most recent update for each key" |
| `log_segment` | `sstable` | "we can make a simple change to the format of our segment files: we require that the sequence of key-value pairs is sorted by key" |
| `compaction` | `sstable` | "We also require that each key only appears once within each merged segment file (the compaction process already ensures that)" |
| `memtable` | `lsm_tree` | "When a write comes in, add it to an in-memory balanced tree data structure...This in-memory tree is sometimes called a memtable" |
| `sstable` | `lsm_tree` | "Originally this indexing structure was described...under the name Log-Structured Merge-Tree" |
| `lsm_tree` | `bloom_filter` | "the LSM-tree algorithm can be slow when looking up keys that do not exist...storage engines often use additional Bloom filters" |
| `lsm_tree` | `write_amplification` | "Log-structured indexes also rewrite data multiple times due to repeated compaction and merging of SSTables. This effect...is known as write amplification" |
| `b_tree` | `write_ahead_log` | "it is common for B-tree implementations to include an additional data structure on disk: a write-ahead log" |
| `b_tree` | `write_amplification` | "A B-tree index must write every piece of data at least twice: once to the write-ahead log, and once to the tree page itself" |

### Tricky Cases

- **Index (general concept)** — dropped to avoid inflation; specific index types are what matter diagnostically.
- **Secondary index, clustered/covering index** — touched on briefly at the end but not substantively explained. No nodes.
- **Sparse in-memory index** — implementation detail of SSTables. Fold into `sstable`.

---

## Case 4 — OLTP, OLAP, and Data Warehousing

**Source:** Chapter 3 — Transaction Processing or Analytics, Data Warehousing, Column-Oriented Storage

### Source Text

```
Transaction Processing or Analytics?
Even though databases started being used for many different kinds of data, the basic
access pattern remained similar to processing business transactions. An application
typically looks up a small number of records by some key, using an index. Because these
applications are interactive, the access pattern became known as online transaction processing (OLTP).
However, databases also started being increasingly used for data analytics, which has
very different access patterns. Usually an analytic query needs to scan over a huge number
of records, only reading a few columns per record, and calculates aggregate statistics.
In order to differentiate this pattern of using databases from transaction processing, it has
been called online analytic processing (OLAP).

Data Warehousing
These OLTP systems are usually expected to be highly available and to process transactions
with low latency. Database administrators are usually reluctant to let business analysts run
ad hoc analytic queries on an OLTP database, since those queries are often expensive.
A data warehouse, by contrast, is a separate database that analysts can query to their
hearts' content, without affecting OLTP operations. The data warehouse contains a read-only
copy of the data in all the various OLTP systems in the company.
Data is extracted from OLTP databases, transformed into an analysis-friendly schema,
cleaned up, and then loaded into the data warehouse. This process of getting data into the
warehouse is known as Extract-Transform-Load (ETL).

Stars and Snowflakes: Schemas for Analytics
Many data warehouses are used in a fairly formulaic style, known as a star schema
(also known as dimensional modeling).
At the center of the schema is a so-called fact table. Each row of the fact table represents
an event that occurred at a particular time.
Other columns in the fact table are foreign key references to other tables, called dimension tables.
As each row in the fact table represents an event, the dimensions represent the who, what,
where, when, how, and why of the event.
A variation of this template is known as the snowflake schema, where dimensions are further
broken down into subdimensions. Snowflake schemas are more normalized than star schemas,
but star schemas are often preferred because they are simpler for analysts to work with.

Column-Oriented Storage
Although fact tables are often over 100 columns wide, a typical data warehouse query
only accesses 4 or 5 of them at one time.
The idea behind column-oriented storage is simple: don't store all the values from one row
together, but store all the values from each column together instead. If each column is stored
in a separate file, a query only needs to read and parse those columns that are used in that query.

Column Compression
Besides only loading those columns from disk that are required for a query, we can further
reduce the demands on disk throughput by compressing data. Column-oriented storage often
lends itself very well to compression. One technique that is particularly effective in data
warehouses is bitmap encoding.

Writing to Column-Oriented Storage
Fortunately, we have already seen a good solution: LSM-trees. All writes first go to an
in-memory store, where they are added to a sorted structure and prepared for writing to disk.

Aggregation: Data Cubes and Materialized Views
Data warehouse queries often involve an aggregate function, such as COUNT, SUM, AVG, MIN, or MAX.
Why not cache some of the counts or sums that queries use most often?
One way of creating such a cache is a materialized view. A materialized view is an actual
copy of the query results, written to disk.
A common special case of a materialized view is known as a data cube or OLAP cube.
It is a grid of aggregates grouped by different dimensions.
```

### Expected Concepts

| id | label | notes |
|---|---|---|
| `oltp` | OLTP (Online Transaction Processing) | Fully defined; low-latency reads/writes, small number of records |
| `olap` | OLAP (Online Analytic Processing) | Fully defined; aggregate queries over large datasets |
| `data_warehouse` | Data Warehouse | Fully explained as separate system for analytics |
| `etl` | ETL (Extract-Transform-Load) | Defined as the process of getting data into the warehouse |
| `star_schema` | Star Schema | Fully explained with fact and dimension tables |
| `snowflake_schema` | Snowflake Schema | Defined as a normalized variation of star schema |
| `fact_table` | Fact Table | Core component of star schema; each row is an event |
| `dimension_table` | Dimension Table | Defined in relation to fact table |
| `column_oriented_storage` | Column-Oriented Storage | Fully explained as solution to analytic query performance |
| `column_compression` | Column Compression | Optimization on top of column-oriented storage; bitmap encoding is an implementation detail, not a separate node |
| `materialized_view` | Materialized View | Fully explained as a cached query result |
| `data_cube` | Data Cube (OLAP Cube) | Defined as a special case of materialized view |

### Expected Edges

| from | to | evidence |
|---|---|---|
| `oltp` | `olap` | "databases also started being increasingly used for data analytics, which has very different access patterns" |
| `olap` | `data_warehouse` | "A data warehouse, by contrast, is a separate database that analysts can query to their hearts' content, without affecting OLTP operations" |
| `etl` | `data_warehouse` | "This process of getting data into the warehouse is known as Extract-Transform-Load (ETL)" |
| `data_warehouse` | `star_schema` | "Many data warehouses are used in a fairly formulaic style, known as a star schema" |
| `star_schema` | `fact_table` | "At the center of the schema is a so-called fact table" |
| `star_schema` | `dimension_table` | "Other columns in the fact table are foreign key references to other tables, called dimension tables" |
| `fact_table` | `dimension_table` | "Other columns in the fact table are foreign key references to other tables, called dimension tables" |
| `star_schema` | `snowflake_schema` | "A variation of this template is known as the snowflake schema, where dimensions are further broken down into subdimensions" |
| `data_warehouse` | `column_oriented_storage` | "a typical data warehouse query only accesses 4 or 5 of them at one time" |
| `column_oriented_storage` | `column_compression` | "we can further reduce the demands on disk throughput by compressing data...column-oriented storage often lends itself very well to compression" |
| `data_warehouse` | `materialized_view` | "data warehouse queries often involve an aggregate function...Why not cache some of the counts or sums that queries use most often? One way of creating such a cache is a materialized view" |
| `materialized_view` | `data_cube` | "A common special case of a materialized view is known as a data cube or OLAP cube" |

### Tricky Cases

- **Row-oriented storage** — mentioned as contrast to column-oriented storage but not taught as a concept. No node.
- **Bitmap encoding / vectorized processing** — implementation details within column-oriented storage. Fold into `column_oriented_storage` and `column_compression`.
- **`fact_table` → `dimension_table` and `star_schema` → both** — redundancy is intentional; a student can understand star schema at surface level without grasping the fact/dimension distinction.

> Note: the original `data_warehouse → column_oriented_storage` evidence quote referenced OLTP indexing algorithms not being "very good at answering analytic queries" — that sentence doesn't appear in the source text excerpt above, so the evidence here has been tightened to a quote that actually appears in this text (the fact-table-width sentence). If the real source text differs from this excerpt, re-derive the quote.
