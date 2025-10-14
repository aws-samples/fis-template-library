"""Configuration settings for Redis stress testing"""

# Redis CLI settings
REDIS_CLI_TIMEOUT = 30
MAX_KEYS_PER_BATCH = 10000

# Memory stress settings  
DEFAULT_MAX_MEMORY = "100mb"
DEFAULT_EVICTION_POLICY = "allkeys-lru"

# Benchmark settings
BENCHMARK_OPERATIONS = 200000
BENCHMARK_RANDOM_KEYS = 1000000
BENCHMARK_PIPELINE = 8
