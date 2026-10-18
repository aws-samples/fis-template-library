# AWS 故障注入服务实验：ElastiCache 复制停滞

本目录是一个配合 AWS Fault Injection Service (FIS) 与 fis-template-library-tooling 使用的实验模板。使用前需要先部署到你的 AWS 账号，并且账号里要有可供注入故障的资源。

> English version: [README.md](README.md).

**本模板会注入真实故障。** 软件按「现状」提供，不附带任何形式的明示或默示担保，包括但不限于对适销性、特定用途适用性和非侵权性的担保。在任何情况下，作者或版权持有人均不对任何索赔、损害或其他责任负责，无论是在合同诉讼、侵权诉讼还是其他诉讼中，由软件或软件的使用或其他交易引起、与之相关或由此产生。

> 免责声明的权威版本是英文 README 中逐字固定的那一段，本段为便于阅读的中文翻译。

## 假设（Hypothesis）

当一个只读副本停止应用复制流、而复制链路仍然保持连接时：应用应当继续以不变的延迟从该副本提供读服务，写入在主节点上正常进行（前提是 `min-replicas-to-write` 为默认值 `0`，见前提 17），并且监控能够发现不断扩大的复制差距，而不是把集群报成健康。

本实验专门用来暴露两类失效：

1. **看起来健康的陈旧读。** 副本仍以正常延迟响应读请求，但返回的数据冻结在停滞开始的那一刻。如果应用把「副本响应很快」等同于「副本数据是最新的」，它会在没有任何报错的情况下对外提供陈旧数据。
2. **监控盲区。** 复制流停滞期间，主节点在 `INFO replication` 里对该副本报出的 `lag` 仍然是 `0`——因为这个字段衡量的是「最近一次收到确认包有多久」，而不是「副本落后了多少」。仅建立在该字段或 `connected_slaves` 上的监控看不见这个故障。真正能看见差距的是主节点侧的 `master_repl_offset` 减去该副本的 `offset`，以及 CloudWatch 的 `ReplicationLag` 指标。

如果故障持续足够久、积压超过副本能承载的量，复制链路会断开，副本随后执行一次全量重同步。这个升级由积压总量驱动，而积压总量约等于**写入速率 × 暂停时长**。

## 前提条件（Prerequisites）

运行本实验之前，请逐项确认：

### 一、目标缓存集群

1. 目标是**节点型**（non-serverless）的 ElastiCache 复制组，引擎为 **Valkey** 或 **Redis OSS**。Serverless 不支持：`client pause` 属于 ElastiCache 对 serverless 缓存禁用的命令。
2. **集群模式关闭与集群模式开启都支持。** 集群模式开启时，首次运行请把 `TargetShardId` 设成单个分片——见下方「分片集群上的爆炸半径」。
3. 该复制组**至少有一个副本**，且 `Status` 为 `available`。副本跨可用区时，实验与真实的 AZ 间网络事件最接近。
4. 集群**未启用** auth token 或 RBAC 认证。本文档不带凭证连接；若缓存返回 `NOAUTH` 或 `WRONGPASS`，脚本会以明确的错误信息退出。如果必须针对带认证的集群运行，需要自行扩展文档，从 AWS Secrets Manager 读取令牌。
5. 如果复制组启用了**传输加密**，需要把文档参数 `UseTls` 设为 `true`。在集群模式开启时这还额外要求实例配置文件具备 `elasticache:DescribeCacheClusters`——因为 `CLUSTER SHARDS` 返回的节点端点是 IP 地址，而 TLS 证书无法针对 IP 校验。文档会从 API 解析节点 DNS 名，若在 `UseTls=true` 时只能拿到 IP，会**失败即关闭并给出明确错误**。

> ### 两种集群模式的发现路径
>
> AWS API 参考明确说明，`DescribeReplicationGroups` 的两个字段**仅在集群模式关闭的
> 复制组上才填充**：
>
> - `NodeGroupMember.CurrentRole` —— "This member is only applicable for Valkey
>   or Redis OSS (cluster mode disabled) replication groups."
> - `NodeGroupMember.ReadEndpoint` —— "The read endpoint is only applicable on
>   Valkey or Redis OSS (cluster mode disabled) clusters."
>
> 这一点已在一个真实的 3 分片集群模式开启复制组上核实：每个成员返回的
> `CurrentRole` 与 `ReadEndpoint` 都是 `null`，而 `NodeGroupId` 与 `Slots` 有值。
>
> 因此文档使用两条发现路径：
>
> | 模式 | 角色与端点来源 | 分片标识来源 |
> |---|---|---|
> | 集群模式关闭 | `NodeGroupMember.CurrentRole` / `ReadEndpoint` | `NodeGroupId` |
> | 集群模式开启 | 配置端点上的 `CLUSTER SHARDS` | 由哈希槽经 `NodeGroups[].Slots` 反查 `NodeGroupId` |
>
> `cluster shards` 与 `cluster nodes` 都不在 ElastiCache 的受限命令清单里。两种模式下
> 被选中的节点都还必须在自己的 `INFO replication` 里报告 `role:slave` 才会被注入，
> 即要求控制面视角与数据面视角一致。
>
> **故障本身与模式无关。** `CLIENT PAUSE` 在集群模式下同样是节点级的：pause 状态存放在
> 单进程的 `server` 结构里，引擎中唯一与集群相关的用法是节点在手动 failover 时暂停
> 自己。暂停某一个分片的副本不会影响其他分片。

### 分片集群上的爆炸半径

`ReplicaScope` 是**按分片**计数的，所以在「每分片一个副本」这种常见拓扑上，
`ONE_PER_SHARD` 与 `ALL` 解析出的集合完全相同——即集群里的全部副本。在
3 shards × 2 nodes 上这意味着整个副本层同时停滞，实验也就没有任何未受影响的分片可供
对比。

**用 `TargetShardId` 只注入一个分片，其余分片留作实验内对照组。** 无论是否定向，
观测都会覆盖**全部**分片的主节点——正是为了让未被定向的分片充当这个对照。

### 二、注入机 EC2 实例

故障是通过缓存的数据面注入的，因此必须从 VPC 内部发起。SSM Automation 的 `aws:executeScript` 运行在 AWS 托管沙箱中、没有 VPC 连通性，因此到不了缓存节点——这正是本模板采用 `aws:ssm:send-command` 打你自己的实例的原因。

5. 你在缓存集群所在的**同一个 VPC** 内有至少一台 **Linux** EC2 实例，且其子网与缓存节点之间网络可达。本文档仅支持 Linux：每个步骤都带 `platformType: Linux` 前置条件。
6. 该实例是**受管实例**：已安装并运行 **3.0.502 或更高版本**的 SSM Agent（文档使用的 `onFailure` / `finallyStep` 步骤控制需要该版本），实例在 Systems Manager 的 Fleet Manager 中可见。文档的 `Region` 参数默认取实例自身所在的 Region（从实例元数据服务读取），因此除非显式传入 `Region`，注入机需要能访问 IMDS。
7. 该实例的实例配置文件（instance profile）**同时具备**：
   - AWS 托管策略 `AmazonSSMManagedInstanceCore`，以及
   - `elasticache:DescribeReplicationGroups`（文档用它读取拓扑）**以及** `elasticache:DescribeCacheClusters`（集群模式开启时用它解析节点 DNS 名）。示例策略见 `elasticache-replication-stall-injector-instance-policy.json`。
8. 该实例所在子网能够访问 **ElastiCache API 端点**——通过 NAT 网关，或者通过 `com.amazonaws.<region>.elasticache` 的接口型 VPC 端点。缺少这条路径时，角色解析步骤会失败，实验会在注入任何东西之前停止。
9. 实例上有 `python3` 和 `aws` CLI。Amazon Linux 2023 与 Amazon Linux 2 都自带这两者。**不需要任何 pip 包，也不需要访问 PyPI 的外网**：内嵌脚本仅用 Python 标准库实现缓存的通信协议。
10. 实例同时打了 `FIS-Ready=True` **和** `FIS-Role=ElastiCacheInjector` 两个标签。第二个标签用于避免把命令误发给那些只带着本仓库通用 `FIS-Ready` 标签的无关实例。

### 三、注入机到缓存的网络路径

11. 缓存集群的安全组**允许来自注入机实例所属安全组的、缓存端口（默认 6379）的入站 TCP**。没有这条规则时，校验步骤会因连接超时而失败。

### 四、IAM 与 SSM 文档

12. 已在账号里用 `elasticache-replication-stall-ssm-template.yaml` 注册名为 `ElastiCacheReplicationStall` 的 SSM 文档：

    ```bash
    aws ssm create-document \
      --name ElastiCacheReplicationStall \
      --document-type Command \
      --document-format YAML \
      --content file://elasticache-replication-stall-ssm-template.yaml
    ```

13. 实验模板 `roleArn` 字段引用的 IAM 角色已存在、信任 `fis.amazonaws.com`（见 `fis-iam-trust-relationship.json`），并挂载了 `elasticache-replication-stall-iam-policy.json` 中的权限。
14. 已替换 `elasticache-replication-stall-template.json` 里的全部占位符：`<YOUR REGION>`、`<YOUR AWS ACCOUNT>`、`<YOUR ROLE NAME>`、`<YOUR REPLICATION GROUP ID>`。

### 五、注入之前的可观测性准备

15. 已对 `ReplicationLag`、`ReplicationBytes`、读延迟、读错误率采集了**至少 10 分钟的稳态基线**。没有基线就无法把故障的影响与正常波动区分开。
16. 实验期间**有写入流量打向主节点**。没有写入，副本就无从落后，即便注入成功，实验也会显示「没有影响」。
17. 你清楚目标参数组里 `min-replicas-to-write` 的取值。默认 `0` 时，主节点不会因为副本状况拒绝任何写入。设为 `1` 或更高时，重写入负载下的持续停滞会让主节点**拒写的时间远长于暂停本身**：验证中 30 秒的暂停导致写入被全部拒绝 **166.8 秒**。单纯的停滞不会触发这道闸门——它衡量的是 ACK 是否及时到达，而暂停期间 ACK 照常发送。只有积压堆满副本内存、节点开始换页并停止发 ACK 时才会触发；之后主节点在 `repl-timeout`（60 秒）断开链路，拒写一直持续到全量重同步完成。取值非 0 时，应把爆炸半径视为已扩大到主节点的写路径。

## 工作原理（How it works）

实验向一台打了标签的注入机发送一个 SSM Command 文档，文档分三步执行。

**ValidatePrerequisites（校验前提）**——把辅助脚本写到实例上，然后执行下列检查。该步骤设置了 `onFailure: exit`，任何一项检查失败，`InjectReplicationStall` 都会被跳过，不会暂停任何节点。

- 解析拓扑并挑选目标节点：集群模式关闭时依据 `CurrentRole`，集群模式开启时依据 `CLUSTER SHARDS`。角色无法证明为 `replica` 的节点会被跳过并告警，**绝不会被暂停**。这是刻意的「失败即关闭」设计：暂停主节点会造成远大于被测范围的故障，而且节点名在发生过故障转移之后并不能可靠地反映角色。
- 连接每个候选节点，确认节点自己也报告 `role:slave`，即要求 API 视角与数据面视角必须一致。
- 发一次 `CLIENT PAUSE 1 <mode>` 作为可用性探针。1 毫秒不会产生可测量的影响，但能在真正注入之前证明该命令在这个集群上是放行的。
- 如果实例上还残留着上一次运行的状态文件，直接拒绝启动。

**InjectReplicationStall（注入）**——先记录主节点侧的视图，然后对每个已解析出的副本执行 `CLIENT PAUSE <PauseMilliseconds> <PauseMode>`（`DutyCyclePercent` 大于 0 时改为周期性的短暂停，见[占空比模式](#占空比模式)），随后在 `DurationSeconds` 期间持续采样主节点的 `INFO replication`，把 `master_repl_offset` 与每个副本已确认的 `offset`、`lag`、`state` 一并记入日志。

观测取自**主节点**而不是副本，因为 `PauseMode=ALL` 会把被暂停副本上的 `INFO` 也一起挂住。

**RestoreAndVerify（恢复与核验）**——执行 `CLIENT UNPAUSE`，报告 `master_link_status`、`master_sync_in_progress` 与副本 offset，再打印一次主节点侧视图，最后删除状态文件和辅助脚本。它是 `finallyStep`，即使校验步骤提前退出也会执行。`CLIENT PAUSE` 会自动到期，所以这一步是安全兜底而非主要恢复手段——即便实验被中断或实例失联，故障也会自愈。

### PauseMode 怎么选

| 你的应用 | 用哪个 | 原因 |
|---|---|---|
| 从副本读 | `WRITE` | 挂住复制流，同时副本继续提供读服务——这正是你要测的状态。 |
| 只从主节点读 | `ALL` | 更干脆，且应用的读路径不经过被暂停的节点。 |

**应用从副本读时不要用 `ALL`**：整个暂停期间该节点上的读请求都被阻塞，这会把「复制落后」和「一个读节点被摘出服务」两件事混在一起，导致结果无法归因。

### 严重程度怎么调

严重程度由积压总量决定，约等于写入速率 × 暂停时长。建议从较短的 `PauseMilliseconds` 起步再逐步加大，这样可以从「应用察觉不到的停滞」，走到「副本被报告为落后」，再走到「复制链路断开并全量重同步」。每次只改一个变量，以保证每一档的结果都可归因。

**在小规格节点上，升级会比预期来得更快。** 在 `cache.t4g.micro` 上的一次验证运行中（3 个写入线程、每个 value 1 KiB），仅 **20 秒**的 `PauseMode=WRITE` 暂停就在主节点侧产生了下面这个序列：

```
master_repl_offset=109213724521  slave0(offset=109021347493, lag=3s,  state=online)
master_repl_offset=109218366559  slave0(offset=109021347493, lag=28s, state=online)   <- 已确认 offset 冻结
...
slave0(offset=0, lag=0s, state=wait_bgsave)   <- 链路断开，进入全量重同步
```

副本已确认的 offset 全程冻结而主节点持续推进，暂停期间链路始终为 `online`；随后积压超过该节点能承载的量——`sync_full` 计数递增，副本最多落后 1.45 GB，之后才追平。**暂停时长要对着节点规格和写入速率来定，不能只看时钟。**

另外，`RestoreAndVerify` 步骤在设计上就是「尽力而为」。同一次运行中 `CLIENT UNPAUSE` 因副本过载而超时，文档记录了告警并继续执行。恢复并不依赖这次调用——暂停会自行到期。

### 占空比模式

`CLIENT PAUSE` 是二值的：复制流要么被挂住，要么没有。把 `DutyCyclePercent` 设为 1-99，可以模拟部分降级。文档会在每个 `CyclePeriodMilliseconds` 开始时下发 `CLIENT PAUSE <周期 × 百分比 / 100> <PauseMode>`，暂停自行到期后进入下一个周期，持续 `DurationSeconds`。副本反复落后、反复追上，这比「一次长时间冻结后一次性追平」更接近被丢包或限流拖慢的复制链路。此模式下 `PauseMilliseconds` 不生效。

两个参数分别控制什么（`cache.t4g.micro`，写入约 12 MiB/s 实测）：

| 参数 | 控制 | 实测 |
|---|---|---|
| `CyclePeriodMilliseconds` × `DutyCyclePercent` / 100，即暂停片长 | 每个周期的积压峰值，约等于写入速率 × 暂停片长 | 4000 ms 的 50%：每个周期峰值 32-37 MiB，回落到 0-3 MiB；基线峰值 10-11 MiB |
| `DutyCyclePercent` | 复制流被挂住的时间占比 | 请求 50% / 75%，实际 50.0% / 75.0% |

**平均吞吐不是旋钮。** 同一组测量中，占空比一直到 90%，副本平均都能跟上，因为它在间隙里应用积压的速度远快于写入到达的速度。要让副本平均跟不上，需要写入接近副本的应用速度，或者占空比接近 100%，也就是单次暂停模式。

此模式下的安全措施：

- 每次下发暂停前，都会在数据面重新读取副本的角色。如果节点不再报告 `role:slave`（例如发生故障转移后被提升为主），它会被移出注入，而不是被当作主节点暂停。
- 如果循环落后于计划（副本响应慢，或观测耗时超过间隙），错过的周期直接跳过，绝不连续补发。结束时会报告实际占空比与跳过的周期数。
- 观测采样放在暂停片即将到期的时刻，也就是积压峰值处。若在暂停片开始时采样，只会看到锯齿的波谷。
- FIS 动作的 `duration` 要覆盖 `DurationSeconds` 加上校验与恢复两步的时间。模板默认的 `PT3M` 是按单次暂停的默认值配的。

**CloudWatch 看不到短暂停片。** 以 4000 ms 的 50% 运行 60 秒期间，被暂停副本的 CloudWatch `ReplicationLag` 最大值一直是 0.001-0.009 秒，而 offset 差每个周期都涨到 37 MiB。几秒级的停滞，`ReplicationLag` 和 `INFO replication` 的 `lag` 字段都分辨不出来。请使用主节点上的 `master_repl_offset` 减去副本 `offset`（文档会记录这个值），或应用自身的数据新鲜度信号。

### `min-replicas-to-write` 的取值如何改变结果

主节点在执行每条写命令之前，统计满足以下两个条件的副本数：状态为 `online`，**并且**在 `min-replicas-max-lag` 秒内发过 ACK。这个数少于 `min-replicas-to-write` 时，写入会被拒绝，返回 `-NOREPLICAS`。集群模式下，每个主节点只统计自己的副本，所以这道闸门是按分片生效的。另外要注意，它判断的是 ACK 是否按时到达，而不是副本落后了多少。

以每分片 1 个副本的拓扑为例：

| 场景 | `0`（默认） | `1` | `2` |
|---|---|---|---|
| 正常运行 | 接受写入 | 接受写入 | **全部拒写**：一个分片永远凑不够两个副本 |
| 某个副本停止发 ACK | 接受写入 | 该分片拒写 | 拒写 |
| 故障转移后，补位副本完成同步之前 | 接受写入 | 该分片拒写（按上述规则推断，未实测） | 拒写 |
| 节点替换或维护期间 | 接受写入 | 可能拒写 | 拒写 |

需要注意的几点：

- **`2` 只在每分片至少 3 个节点时才有意义。** 每分片只有 1 个副本时，设成 `2` 等于关闭写入。
- **它不是同步复制。** 它保证的是有足够多的副本最近回过 ACK，并不保证某一条写入已经到达这些副本。它把数据丢失窗口限制在大约 `min-replicas-max-lag` 秒之内，但没有消除这个窗口。需要逐条写入的保证，请用 `WAIT`（节点型缓存可用，本模板未实测）。
- **本实验会低估这道闸门的作用。** `CLIENT PAUSE` 不影响 ACK 的发送，所以闸门看到的副本一直是健康的。验证中，取值为 `0` 时，11 分钟的停滞期间所有写入都被接受，而主节点上积压了 166 MiB 副本没有的数据。取值为 `1` 时，单纯暂停不会触发闸门；只有副本内存耗尽、停止发 ACK 之后，闸门才触发。真实丢包不一样：ACK 走的也是同一条变差的链路，`lag` 会真实增长，闸门更容易触发。如果生产环境设的是 `1` 或更高，网络事件期间出现的拒写很可能就来自这道闸门。要复现这种情况，需要让 ACK 也停下来，例如在隔离环境中用 `aws:network:disrupt-connectivity` 切断复制路径。

| 目标 | 设置 | 代价 |
|---|---|---|
| 写入可用性优先（缓存通常如此） | `0` | 故障转移时可能丢失副本尚未收到的写入，丢失量没有上限 |
| 限制故障转移时的数据丢失 | `1`，并且每分片至少 2 个副本 | 副本不健康或正在被替换时，该分片停止接受写入 |
| `2` | 仅适用于每分片至少 3 个节点、且对一致性要求很高的场景 | 任意一个副本不健康，该分片就停止接受写入 |

### 恢复手段：加一个副本

副本跟不上时，常见的预案是用 `increase-replica-count` 再加一个副本。这样能不能恢复写入，取决于写入失败的原因。请把它作为单独一步来测，并按下面几点解读结果。

**实测了什么。** 在集群模式开启的复制组上，让某个分片唯一的副本持续停滞（反复下发 `CLIENT PAUSE WRITE`），同时往该分片写入，然后在主节点所在 AZ 申请增加一个副本：

| 距 API 调用 | 事件 |
|---|---|
| 0.5 秒 | `increase-replica-count` 被接受，复制组进入 `modifying`。**分片处于降级状态不会阻止这个请求** |
| 0 – 488 秒 | 节点置备中，数据面没有变化；停滞副本的积压持续增长 |
| 488 秒 | 新副本出现在主节点视图，状态 `wait_bgsave`，`sync_full` 递增（一个副本触发了两次，原因没查明） |
| **555.6 秒** | 新副本 `online` |
| 576 秒 | 复制组回到 `available`；停滞的副本仍落后约 160 MiB，状态仍是 `state=online` |

随后解除停滞，原副本 10 秒内追完 166 MiB，没有重同步。全程没有任何写入失败。

**对写入意味着什么。**

- **`min-replicas-to-write` 为默认值 `0` 时，新副本没有可恢复的东西。** 11 分钟的停滞期间，主节点没有拒绝过任何写入。
- **设为 `1` 或更高时，新副本可以恢复写入，但必须等它 `online`。** 闸门只计入状态为 `online`、且在 `min-replicas-max-lag` 内发过 ACK 的副本。故障期间新加的副本，要等全量同步完成才会被计入。本次用了 **9 分 15 秒**（`cache.t4g.micro`，数据约 20 MiB），数据集越大越久。在此之前写入一直被拒。
- **故障可能先自己恢复。** 开启 `min-replicas-to-write=1` 时，重写入下 30 秒的暂停导致拒写 166.8 秒，之后自行恢复：链路在 `repl-timeout` 时断开，副本随后完成重同步。这只有新副本上线所需时间的约三分之一。实验时要比较「写入恢复」和「新副本 `online`」两个时刻；如果写入先恢复，就不是新副本的作用。
- **如果瓶颈在网络，新副本反而加压。** 新副本的全量同步（生成并传输 RDB）占用的正是主节点的出向带宽。如果写入失败是因为 `NetworkBandwidthOutAllowanceExceeded` 而不是 `-NOREPLICAS`，加副本会让情况更糟。
- **想尽快恢复写入，把 `min-replicas-to-write` 调成 `0` 更快。** 代价是用持久性换可用性。该参数的 `ChangeType` 是 `immediate`（无需重启），但在各次验证中到达 `in-sync` 用了 86 到 147 秒不等。

未实测：「写入被拒 → 加副本 → 新副本 `online` 后写入恢复」这一完整过程。要直接测，可以把 `min-replicas-to-write` 设得比该分片当前副本数大，让写入因配置被拒，然后加副本，测量从 `online` 到第一次写入成功之间的间隔。这能单独验证这条恢复路径，但不是对复制停滞的复现。

## 验证记录（Validation）

已在 `ap-northeast-1` 的两个真实复制组上端到端验证，均为 `cache.t4g.micro` 上的
**Valkey 8.2**。

**集群模式关闭**（主节点在 `ap-northeast-1a`、副本在 `ap-northeast-1c`）。在有写流量的
情况下，副本已确认的 offset 冻结而主节点持续推进，链路始终 `online`：

```
master_repl_offset=109213724521  slave0(offset=109021347493, lag=3s,  state=online)
master_repl_offset=109218366559  slave0(offset=109021347493, lag=28s, state=online)
```

**集群模式开启**（3 shards × 2 nodes）。`TargetShardId=0002`、`PauseMode=WRITE`、
25 秒暂停、集群感知的写负载铺满所有槽位。只有被定向的分片停滞，另两个分片全程跟随
各自主节点，充当对照组：

| 时刻 | 分片 0001 副本 | **分片 0002 副本** | 分片 0003 副本 |
|---|---|---|---|
| +6s | 82952549 | **66163374** | 83108186 |
| +12s | 104020083 | **66163374** | 104258492 |
| +18s | 124803283 | **66163374** | 125022580 |
| +24s | 145465515 | **66163374** | 145678460 |
| +30s | 166522453 | 166227863（已追平） | 166731140 |

暂停到期后，分片 0002 的副本应用了约 100 MB 积压，恢复到
`master_link_status=up`、`master_sync_in_progress=0`。

**持续的监控盲区。** 在同一个分片集群上，把一个分片的副本连续冻结 11 分钟。期间主节点 `INFO replication` 的 `lag` 一直是 0-1 秒、`state=online`，复制组保持 `available`；而该副本的 CloudWatch `ReplicationLag` 从 52 秒涨到 592 秒，每分钟涨 60 秒，未被定向的分片全程 0.001 秒。

**开启 `min-replicas-to-write=1` 时的拒写**（集群模式关闭，4 个写入线程 × 4 KiB × pipeline 50，定长键空间 80 MiB，`PauseMode=ALL`，暂停 30 秒）：注入后 15.3 秒出现首个 `-NOREPLICAS`，之后全部写入被拒，直到第 183 秒。副本 `SwapUsage` 从 176 MiB 涨到 323 MiB，而引擎 CPU 只有 0-5%；链路约在第 73 秒断开，全量重同步完成后才恢复。

**占空比模式。** 集群模式关闭，`DutyCyclePercent=50`、`CyclePeriodMilliseconds=4000`、40 秒，定长键空间写入约 12 MiB/s：下发 10 次暂停、0 次失败，实际占空比 50.0%；副本 offset 差峰值 37 MiB（基线 10 MiB），链路始终 `online`，写入 0 失败。集群模式开启，对有两个副本的分片设 `TargetShardId=0002`、`DutyCyclePercent=75`，向该分片写入约 8 MiB/s：被定向的副本峰值 31 MiB，同分片另一个副本保持在 7.5 MiB 的基线。同一集群上的单次暂停（`DutyCyclePercent=0`）行为与之前一致。

另外还验证了：幂等闸门会拒绝第二次 `validate`；不存在的 `TargetShardId` 会在注入任何
东西之前被拒绝；**没有写流量**的运行正确地显示无复制差距——这正是「必须有写流量」被
列为硬性前提的原因。

## 停止条件（Stop Conditions）

本实验没有定义特定的停止条件。它会持续运行，直到被手动停止，或者暂停到期且目标实例上的 RestoreAndVerify 步骤执行完毕。

停止条件基于 AWS CloudWatch 告警，由需要立即结束故障注入的运维指标或业务指标驱动。本模板不对你的应用及其相关指标做任何假设，因此默认不包含停止条件。

## 后续建议（Next Steps）

在把这个场景改造成适合你自己的版本时，建议：

1. 复核你使用的标签名是否契合自身场景。本模板刻意要求注入机同时具备 `FIS-Ready=True` 与 `FIS-Role=ElastiCacheInjector` 两个标签，以免命令被发给无关实例。
2. 识别与缓存读取相关的业务指标——例如缓存命中率、读延迟，以及任何能暴露陈旧读的正确性信号。
3. 创建 CloudWatch 指标与告警来监控复制停滞的影响。持续几十秒以上的停滞，首选信号是 `ReplicationLag`；它分辨不出占空比模式下几秒级的暂停片，该模式请改用 offset 差告警。**不要**把告警建在 `INFO replication` 的 `lag` 字段或 `connected_slaves` 上：复制流停滞期间这两者都不动。
4. 把告警接成停止条件，以便在越过关键阈值时自动中止实验。
5. 先在非生产环境运行，并在那里先确认 `CLIENT PAUSE` 在你的集群与引擎版本上确实放行，之后再考虑安排到其他环境。
6. 如果你的集群使用 auth token 或 RBAC，扩展本文档以从 AWS Secrets Manager 读取令牌。
7. 把本实验与 `elasticache-az-power-interruption` 搭配使用，以覆盖突发失效。本模板覆盖的是链路尚在的渐进式退化，后者覆盖的是节点直接消失。

## 导入实验（Import Experiment）

你可以通过 CLI 或 AWS CDK 把 json 实验模板导入 AWS 账号。分步说明请见 [fis-template-library-tooling](https://github.com/aws-samples/fis-template-library-tooling)。

## 本目录文件说明

| 文件 | 用途 |
|---|---|
| `README.md` | 英文说明（权威版本，含逐字固定的免责声明与停止条件段落） |
| `README.zh-CN.md` | 本文档 |
| `AWSFIS.json` | 模板版本标记 |
| `elasticache-replication-stall-template.json` | FIS 实验模板 |
| `elasticache-replication-stall-ssm-template.yaml` | 执行注入的 SSM Command 文档 |
| `elasticache-replication-stall-iam-policy.json` | FIS 实验角色的策略 |
| `elasticache-replication-stall-injector-instance-policy.json` | 注入机实例配置文件的策略（`DescribeReplicationGroups` + `DescribeCacheClusters`） |
| `fis-iam-trust-relationship.json` | FIS 实验角色的信任关系 |
