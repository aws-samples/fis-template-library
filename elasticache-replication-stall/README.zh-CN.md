# AWS 故障注入服务实验：ElastiCache 复制停滞

本目录是一个配合 AWS Fault Injection Service (FIS) 与 fis-template-library-tooling 使用的实验模板。使用前需要先部署到你的 AWS 账号，并且账号里要有可供注入故障的资源。

> English version: [README.md](README.md).

**本模板会注入真实故障。** 软件按「现状」提供，不附带任何形式的明示或默示担保，包括但不限于对适销性、特定用途适用性和非侵权性的担保。在任何情况下，作者或版权持有人均不对任何索赔、损害或其他责任负责，无论是在合同诉讼、侵权诉讼还是其他诉讼中，由软件或软件的使用或其他交易引起、与之相关或由此产生。

> 免责声明的权威版本是英文 README 中逐字固定的那一段，本段为便于阅读的中文翻译。

## 假设（Hypothesis）

当一个只读副本停止应用复制流、而复制链路仍然保持连接时：应用应当继续以不变的延迟从该副本提供读服务，写入在主节点上正常进行，并且监控能够发现不断扩大的复制差距，而不是把集群报成健康。

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
6. 该实例是**受管实例**：SSM Agent 已安装并在运行，实例在 Systems Manager 的 Fleet Manager 中可见。
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

## 工作原理（How it works）

实验向一台打了标签的注入机发送一个 SSM Command 文档，文档分三步执行。

**ValidatePrerequisites（校验前提）**——把辅助脚本写到实例上，然后：

- 调用 `elasticache:DescribeReplicationGroups`，依据 API 返回的 `CurrentRole` 字段挑选目标节点。角色不是严格等于 `replica` 的节点会被跳过并告警，**绝不会被暂停**。这是刻意的「失败即关闭」设计：暂停主节点会造成远大于被测范围的故障，而且节点名在发生过故障转移之后并不能可靠地反映角色。
- 连接每个候选节点，确认节点自己也报告 `role:slave`，即要求 API 视角与数据面视角必须一致。
- 发一次 `CLIENT PAUSE 1 <mode>` 作为可用性探针。1 毫秒不会产生可测量的影响，但能在真正注入之前证明该命令在这个集群上是放行的。
- 如果实例上还残留着上一次运行的状态文件，直接拒绝启动。

**InjectReplicationStall（注入）**——先记录主节点侧的视图，然后对每个已解析出的副本执行 `CLIENT PAUSE <PauseMilliseconds> <PauseMode>`，随后在 `DurationSeconds` 期间持续采样主节点的 `INFO replication`，把 `master_repl_offset` 与每个副本已确认的 `offset`、`lag`、`state` 一并记入日志。

观测取自**主节点**而不是副本，因为 `PauseMode=ALL` 会把被暂停副本上的 `INFO` 也一起挂住。

**RestoreAndVerify（恢复与核验）**——执行 `CLIENT UNPAUSE`，报告 `master_link_status`、`master_sync_in_progress` 与副本 offset，再打印一次主节点侧视图，最后删除状态文件。`CLIENT PAUSE` 会自动到期，所以这一步是安全兜底而非主要恢复手段——即便实验被中断或实例失联，故障也会自愈。

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
3. 创建 CloudWatch 指标与告警来监控复制停滞的影响。首选信号是 `ReplicationLag`。**不要**把告警建在 `INFO replication` 的 `lag` 字段或 `connected_slaves` 上：复制流停滞期间这两者都不动。
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
