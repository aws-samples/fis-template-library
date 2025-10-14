import subprocess
import os

class RedisStressOperations:
    """Redis stress operations using bundled redis-cli"""
    
    def __init__(self):
        # Use bundled redis-cli binary
        self.redis_cli = os.path.join(os.path.dirname(__file__), '..', 'redis-cli')
    
    def setup_memory_policy(self, endpoint, port):
        """Set maxmemory and LRU policy as per experiments.md"""
        subprocess.run([
            self.redis_cli, '-h', endpoint, '-p', str(port),
            'CONFIG', 'SET', 'maxmemory', '100mb'
        ], check=True)
        
        subprocess.run([
            self.redis_cli, '-h', endpoint, '-p', str(port),
            'CONFIG', 'SET', 'maxmemory-policy', 'allkeys-lru'
        ], check=True)
        
        print(f"Set maxmemory=100mb and policy=allkeys-lru")
    
    def fill_cache_with_keys(self, endpoint, port, cluster_id):
        """Fill cache with load_test keys as per experiments.md"""
        print(f"Filling cache with 1000 load_test keys")
        
        for i in range(1, 1001):
            subprocess.run([
                self.redis_cli, '-h', endpoint, '-p', str(port),
                'SET', f'load_test:{i}', f'some-payload-{i}'
            ], check=True)
            
            if i % 100 == 0:
                print(f"Created {i} keys")
    
    def apply_benchmark_pressure(self, endpoint, port):
        """Skip benchmark - not available in package"""
        print("Skipping benchmark pressure (not packaged)")
    
    def cleanup_cluster(self, endpoint, port):
        """Clean up all test data"""
        subprocess.run([
            self.redis_cli, '-h', endpoint, '-p', str(port), 'FLUSHALL'
        ], check=True)
